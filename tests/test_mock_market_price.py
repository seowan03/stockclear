import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import Base, ensure_raw_inventory_mock_market_price_column
from app.models import RawInventory, User
from app.routers.inventory import get_export, list_inventory
from app.services.inventory_service import save_inventory_analysis
from app.services.mock_market_price import generate_mock_market_price


class MockMarketPriceTests(unittest.TestCase):
    def test_generated_prices_stay_in_range_and_use_hundred_won_steps_when_possible(self):
        rng = np.random.default_rng(42)
        prices = [generate_mock_market_price(1500, rng) for _ in range(40)]

        self.assertTrue(all(1350 <= price <= 1650 for price in prices))
        self.assertTrue(all(price % 100 == 0 for price in prices))
        self.assertGreater(len(set(prices)), 1)

    def test_missing_or_non_positive_selling_price_has_no_mock_quote(self):
        for selling_price in (None, 0, -100, float("nan"), "not-a-price"):
            with self.subTest(selling_price=selling_price):
                self.assertIsNone(generate_mock_market_price(selling_price))

    def test_small_prices_stay_in_range_when_hundred_won_step_is_not_possible(self):
        price = generate_mock_market_price(120, np.random.default_rng(1))

        self.assertGreaterEqual(price, 108)
        self.assertLessEqual(price, 132)

    def test_migration_adds_column_and_backfills_only_eligible_rows_once(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE raw_inventory (item_id INTEGER PRIMARY KEY, market_price NUMERIC(12, 2))"
            ))
            connection.execute(text(
                "INSERT INTO raw_inventory (item_id, market_price) VALUES "
                "(1, 1500), (2, 0), (3, NULL)"
            ))

        with patch("app.database.engine", engine):
            ensure_raw_inventory_mock_market_price_column()
            with engine.connect() as connection:
                rows = connection.execute(text(
                    "SELECT item_id, market_price, mock_market_price FROM raw_inventory ORDER BY item_id"
                )).fetchall()
            first_quote = rows[0].mock_market_price
            ensure_raw_inventory_mock_market_price_column()
            with engine.connect() as connection:
                repeated_quote = connection.execute(text(
                    "SELECT mock_market_price FROM raw_inventory WHERE item_id = 1"
                )).scalar_one()

        self.assertGreaterEqual(float(first_quote), 1350)
        self.assertLessEqual(float(first_quote), 1650)
        self.assertIsNone(rows[1].mock_market_price)
        self.assertIsNone(rows[2].mock_market_price)
        self.assertEqual(float(repeated_quote), float(first_quote))
        engine.dispose()

    def test_upload_persists_mock_quote_and_exposes_it_without_changing_selling_price(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()
        session.add(User(user_id=1, username="test", email="test@example.com", password_hash="x"))
        session.commit()
        rows = pd.DataFrame([{
            "product_name": "테스트 상품",
            "stock_qty": 3,
            "purchase_price": 1000,
            "selling_price": 1500,
            "received_date": pd.Timestamp("2026-01-01"),
            "sales_qty": 2,
            "sales_speed": 0.1,
            "storage_days": 10,
            "days_to_sell": 30,
            "risk_grade": "정상",
            "inventory_value": 3000,
            "final_score": 10,
            "depreciation_rate": 0,
        }])

        save_inventory_analysis(
            session,
            1,
            "test-batch",
            rows,
            rng=np.random.default_rng(7),
        )
        session.commit()
        saved = session.query(RawInventory).one()
        inventory = list_inventory("", "", None, session, User(user_id=1))
        api_item = inventory["items"][0]

        self.assertEqual(float(saved.market_price), 1500)
        self.assertGreaterEqual(float(saved.mock_market_price), 1350)
        self.assertLessEqual(float(saved.mock_market_price), 1650)
        self.assertEqual(float(saved.mock_market_price) % 100, 0)
        self.assertEqual(api_item["selling_price"], 1500)
        self.assertEqual(api_item["mock_market_price"], float(saved.mock_market_price))
        export = get_export(None, session, User(user_id=1))
        self.assertEqual(export["items"][0]["mock_market_price"], float(saved.mock_market_price))

        session.close()
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
