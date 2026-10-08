import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as database
from app.main import app
from app.models import InventoryDailyMetric, RawInventory, User


class DashboardSalesInsightsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.session_factory = sessionmaker(
            bind=self.engine,
            autocommit=False,
            autoflush=False,
        )

    def tearDown(self):
        self.engine.dispose()

    def _add_item(self, db, user_id, name, stock_qty, daily_sales):
        item = RawInventory(
            user_id=user_id,
            upload_batch_id="sales-insights-test",
            product_name=name,
            stock_qty=stock_qty,
            purchase_price=100,
            market_price=150,
            inbound_date=date.today() - timedelta(days=30),
            created_at=datetime.utcnow(),
            sales_qty=0,
            is_selling=True,
            is_deleted=False,
        )
        db.add(item)
        db.flush()
        db.add_all([
            InventoryDailyMetric(
                item_id=item.item_id,
                business_date=business_date,
                daily_sales_qty=quantity,
                remaining_stock_qty=stock_qty,
                daily_selling_price=150,
                price_variation_rate=0,
            )
            for business_date, quantity in daily_sales
        ])
        return item

    def test_returns_top_three_and_selected_item_daily_series(self):
        with (
            patch.object(database, "engine", self.engine),
            patch.object(database, "SessionLocal", self.session_factory),
            TestClient(app) as client,
        ):
            signup = client.post("/api/auth/signup", json={
                "username": "Sales Test",
                "email": "sales-insights@example.test",
                "password": "test-password",
            })
            self.assertEqual(signup.status_code, 200, signup.text)

            with self.session_factory() as db:
                user_id = db.query(User.user_id).filter_by(email="sales-insights@example.test").scalar()
                today = date.today()
                leading_item = self._add_item(db, user_id, "선두 상품", 12, [
                    (today - timedelta(days=8), 10),
                    (today - timedelta(days=1), 5),
                ])
                self._add_item(db, user_id, "두 번째 상품", 8, [(today - timedelta(days=1), 8)])
                self._add_item(db, user_id, "세 번째 상품", 4, [(today - timedelta(days=1), 3)])
                self._add_item(db, user_id, "네 번째 상품", 2, [(today - timedelta(days=1), 1)])
                db.commit()
                leading_item_id = leading_item.item_id

            response = client.get("/api/dashboard/sales-insights?days=7")
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertEqual([item["product_name"] for item in result["top_items"]], [
                "선두 상품",
                "두 번째 상품",
                "세 번째 상품",
            ])
            self.assertEqual(result["top_items"][0]["sales_qty"], 15)
            self.assertEqual(result["selected_item_id"], leading_item_id)
            self.assertEqual(len(result["dates"]), 7)
            self.assertEqual(result["daily_sales_qty"][-2], 5)
            self.assertIsNone(result["daily_sales_qty"][-1])

    def test_rejects_unsupported_period(self):
        with (
            patch.object(database, "engine", self.engine),
            patch.object(database, "SessionLocal", self.session_factory),
            TestClient(app) as client,
        ):
            client.post("/api/auth/signup", json={
                "username": "Sales Test",
                "email": "sales-period@example.test",
                "password": "test-password",
            })

            response = client.get("/api/dashboard/sales-insights?days=14")
            self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()