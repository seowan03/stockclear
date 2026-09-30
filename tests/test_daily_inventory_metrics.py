import csv
import io
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as database
import app.routers.upload as upload_router
from app.main import app
from app.models import InventoryDailyMetric, RawInventory
from app.services.daily_inventory_service import generate_daily_inventory_metrics
from app.services.upload_service import REQUIRED_COLUMNS


class DailyInventoryMetricsApiTests(unittest.TestCase):
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

    def _csv_file(self, row):
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(REQUIRED_COLUMNS)
        writer.writerow(row)
        return buffer.getvalue().encode("utf-8-sig")

    def _upload(self, client, filename, row):
        return client.post(
            "/api/upload",
            files={"file": (filename, self._csv_file(row), "text/csv")},
        )

    def test_numpy_generation_is_deterministic_for_item_and_date(self):
        first = generate_daily_inventory_metrics(9, 31, date(2026, 9, 1), 150)
        repeated = generate_daily_inventory_metrics(9, 31, date(2026, 9, 1), 150)
        first_values = [
            (row.business_date, row.daily_sales_qty, row.daily_selling_price, row.price_variation_rate)
            for row in first
        ]
        repeated_values = [
            (row.business_date, row.daily_sales_qty, row.daily_selling_price, row.price_variation_rate)
            for row in repeated
        ]
        self.assertEqual(first_values, repeated_values)

    def test_upload_generates_and_upsert_replaces_31_daily_metrics(self):
        with (
            patch.object(database, "engine", self.engine),
            patch.object(database, "SessionLocal", self.session_factory),
            patch.object(upload_router, "get_upload_diagnosis_summary", return_value="test summary"),
            TestClient(app) as client,
        ):
            signup = client.post("/api/auth/signup", json={
                "username": "Daily Metrics User",
                "email": "daily-metrics@example.test",
                "password": "test-password",
            })
            self.assertEqual(signup.status_code, 200, signup.text)

            first_row = ["Daily Item", 10, 100, "2026-09-01", 150, 4]
            first_upload = self._upload(client, "daily-first.csv", first_row)
            self.assertEqual(first_upload.status_code, 200, first_upload.text)
            first_upload_id = first_upload.json()["history_id"]
            item = client.get("/api/inventory").json()["items"][0]
            item_id = item["item_id"]

            with self.session_factory() as db:
                metrics = db.query(InventoryDailyMetric).filter_by(item_id=item_id).order_by(
                    InventoryDailyMetric.business_date
                ).all()
                stored_inventory = db.get(RawInventory, item_id)
                self.assertEqual(stored_inventory.stock_qty, 10)
                self.assertEqual(stored_inventory.sales_qty, 4)
                self.assertEqual(stored_inventory.market_price, Decimal("150.00"))

            self.assertEqual(len(metrics), 31)
            expected_dates = [date(2026, 9, 1) + timedelta(days=offset) for offset in range(31)]
            self.assertEqual([metric.business_date for metric in metrics], expected_dates)
            for metric in metrics:
                self.assertIsInstance(metric.daily_sales_qty, int)
                self.assertGreaterEqual(metric.daily_sales_qty, 0)
                self.assertLessEqual(metric.daily_sales_qty, 20)
                self.assertGreaterEqual(metric.price_variation_rate, Decimal("-0.05"))
                self.assertLessEqual(metric.price_variation_rate, Decimal("0.05"))
                self.assertGreaterEqual(metric.daily_selling_price, Decimal("142.5"))
                self.assertLessEqual(metric.daily_selling_price, Decimal("157.5"))

            first_day_response = client.get(
                "/api/inventory/daily",
                params={"business_date": "2026-09-01", "upload_id": first_upload_id},
            )
            self.assertEqual(first_day_response.status_code, 200, first_day_response.text)
            first_day_item = first_day_response.json()["items"][0]
            self.assertEqual(first_day_item["item_id"], item_id)
            self.assertEqual(first_day_item["daily_sales_qty"], metrics[0].daily_sales_qty)
            self.assertEqual(Decimal(str(first_day_item["daily_selling_price"])), metrics[0].daily_selling_price)
            self.assertEqual(first_day_item["weekday"], "화요일")

            repeated_response = client.get(
                "/api/inventory/daily",
                params={"business_date": "2026-09-01", "upload_id": first_upload_id},
            )
            self.assertEqual(repeated_response.json(), first_day_response.json())
            self.assertEqual(
                client.get("/api/inventory/daily", params={"business_date": "2026-10-02"}).json()["items"],
                [],
            )
            self.assertEqual(
                client.get("/api/inventory/daily", params={"business_date": "not-a-date"}).status_code,
                422,
            )
            with self.session_factory() as db:
                stored_inventory = db.get(RawInventory, item_id)
                self.assertEqual(stored_inventory.stock_qty, 10)
                self.assertEqual(stored_inventory.sales_qty, 4)
                self.assertEqual(stored_inventory.market_price, Decimal("150.00"))

            changed_row = ["Daily Item ", 17, 100, "2026-09-02", 200, 9]
            updated_upload = self._upload(client, "daily-updated.csv", changed_row)
            self.assertEqual(updated_upload.status_code, 200, updated_upload.text)
            updated_item = client.get("/api/inventory").json()["items"][0]
            self.assertEqual(updated_item["item_id"], item_id)
            self.assertEqual(updated_item["received_date"], "2026-09-02")
            self.assertEqual(updated_item["stock_qty"], 17)
            self.assertEqual(updated_item["sales_qty"], 9)

            with self.session_factory() as db:
                updated_metrics = db.query(InventoryDailyMetric).filter_by(item_id=item_id).order_by(
                    InventoryDailyMetric.business_date
                ).all()
                stored_inventory = db.get(RawInventory, item_id)
                self.assertEqual(stored_inventory.stock_qty, 17)
                self.assertEqual(stored_inventory.sales_qty, 9)
                self.assertEqual(stored_inventory.market_price, Decimal("200.00"))

            updated_dates = [date(2026, 9, 2) + timedelta(days=offset) for offset in range(31)]
            self.assertEqual(len(updated_metrics), 31)
            self.assertEqual([metric.business_date for metric in updated_metrics], updated_dates)
            self.assertEqual(
                client.get("/api/inventory/daily", params={"business_date": "2026-09-01"}).json()["items"],
                [],
            )
            updated_upload_id = updated_upload.json()["history_id"]
            scoped_daily = client.get(
                "/api/inventory/daily",
                params={"business_date": "2026-09-02", "upload_id": updated_upload_id},
            )
            self.assertEqual(scoped_daily.status_code, 200, scoped_daily.text)
            self.assertEqual([row["item_id"] for row in scoped_daily.json()["items"]], [item_id])

            identical_upload = self._upload(client, "same-updated-data.csv", changed_row)
            self.assertEqual(identical_upload.status_code, 409)
            with self.session_factory() as db:
                self.assertEqual(db.query(InventoryDailyMetric).filter_by(item_id=item_id).count(), 31)

    def test_daily_endpoint_is_user_scoped_and_date_picker_uses_saved_api(self):
        with (
            patch.object(database, "engine", self.engine),
            patch.object(database, "SessionLocal", self.session_factory),
            patch.object(upload_router, "get_upload_diagnosis_summary", return_value="test summary"),
            TestClient(app) as client,
        ):
            first_signup = client.post("/api/auth/signup", json={
                "username": "First Daily User",
                "email": "first-daily@example.test",
                "password": "test-password",
            })
            self.assertEqual(first_signup.status_code, 200, first_signup.text)
            first_upload = self._upload(
                client,
                "first-daily.csv",
                ["Shared Name", 5, 100, "2026-09-01", 150, 2],
            )
            self.assertEqual(first_upload.status_code, 200, first_upload.text)
            first_item_id = client.get("/api/inventory").json()["items"][0]["item_id"]
            first_upload_id = first_upload.json()["history_id"]

            client.post("/api/auth/logout")
            second_signup = client.post("/api/auth/signup", json={
                "username": "Second Daily User",
                "email": "second-daily@example.test",
                "password": "test-password",
            })
            self.assertEqual(second_signup.status_code, 200, second_signup.text)
            second_upload = self._upload(
                client,
                "second-daily.csv",
                ["Shared Name", 8, 100, "2026-09-01", 150, 3],
            )
            self.assertEqual(second_upload.status_code, 200, second_upload.text)
            second_item_id = client.get("/api/inventory").json()["items"][0]["item_id"]
            self.assertNotEqual(first_item_id, second_item_id)

            second_upload_daily = client.get(
                "/api/inventory/daily",
                params={"business_date": "2026-09-01", "upload_id": second_upload.json()["history_id"]},
            )
            self.assertEqual(second_upload_daily.status_code, 200, second_upload_daily.text)
            self.assertEqual([row["item_id"] for row in second_upload_daily.json()["items"]], [second_item_id])

            foreign_upload_daily = client.get(
                "/api/inventory/daily",
                params={"business_date": "2026-09-01", "upload_id": first_upload_id},
            )
            self.assertEqual(foreign_upload_daily.status_code, 404)
            second_user_daily = client.get(
                "/api/inventory/daily",
                params={"business_date": "2026-09-01"},
            )
            self.assertEqual(second_user_daily.status_code, 200)
            self.assertEqual([row["item_id"] for row in second_user_daily.json()["items"]], [second_item_id])

        inventory_page = Path(__file__).resolve().parents[1] / "static" / "inventory.html"
        source = inventory_page.read_text(encoding="utf-8")
        self.assertIn("/api/inventory/daily?", source)
        self.assertIn("dailyMetric.daily_sales_qty", source)
        self.assertNotIn("getDailyDemoData", source)


if __name__ == "__main__":
    unittest.main()