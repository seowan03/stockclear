import unittest
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import (
    Base,
    ensure_analysis_results_recommended_price_column,
    ensure_raw_inventory_mock_market_price_column,
)
from app.models import AnalysisResult, RawInventory, User
from app.routers.ai import _apply_price_floors, _format_action_plan, diagnose_saved_inventory
from app.routers.inventory import get_export, list_inventory, refresh_inventory_market_price
from app.services.inventory_service import save_inventory_analysis
from app.services.mock_market_price import generate_mock_market_price


class MockMarketPriceTests(unittest.TestCase):
    def test_discount_below_market_but_above_cost_is_allowed(self):
        result = _apply_price_floors(
            {"recommended_discount": 10, "comment": "할인 권장"},
            {"selling_price": 1500, "purchase_price": 1000, "current_market_price": 1400},
        )

        self.assertEqual(result["recommended_discount"], 10)
        self.assertEqual(result["recommended_price"], 1350)
        self.assertLess(result["recommended_price"], 1400)
        self.assertGreaterEqual(result["recommended_price"], 1000)
        self.assertIsNone(result["price_limit_notice"])

    def test_discount_ending_exactly_at_market_price_is_allowed(self):
        result = _apply_price_floors(
            {"recommended_discount": 12.5, "comment": "할인 권장"},
            {"selling_price": 1600, "purchase_price": 1000, "current_market_price": 1400},
        )

        self.assertEqual(result["recommended_discount"], 12.5)
        self.assertEqual(result["recommended_price"], 1400)

    def test_cost_remains_floor_when_cost_is_above_market_price(self):
        result = _apply_price_floors(
            {"recommended_discount": 10, "comment": "할인 권장"},
            {"selling_price": 1100, "purchase_price": 1050, "current_market_price": 900},
        )

        self.assertEqual(result["recommended_discount"], 4.54)
        self.assertGreaterEqual(result["recommended_price"], 1050)

    def test_no_discount_keeps_selling_price_even_when_market_is_higher(self):
        result = _apply_price_floors(
            {"recommended_discount": 0, "comment": "규칙 기반"},
            {"selling_price": 1300, "purchase_price": 1000, "current_market_price": 1400},
        )

        self.assertEqual(result["recommended_discount"], 0)
        self.assertEqual(result["recommended_price"], 1300)

    def test_action_plan_uses_readable_lines_and_sentence_ending(self):
        action_plan = _format_action_plan(
            0,
            13100.0,
            "보관 기간이 길어 회전율이 낮으므로 30% 일괄 할인을 권장합니다",
            "원가 이하로 내려가지 않도록 할인율을 0%로 제한했습니다",
        )

        self.assertEqual(
            action_plan.splitlines(),
            [
                "할인율 0%.",
                "권장 판매가 13,100원.",
                "AI 진단: 보관 기간이 길어 회전율이 낮으므로 30% 일괄 할인을 권장합니다.",
                "조정 사유: 원가 이하로 내려가지 않도록 할인율을 0%로 제한했습니다.",
            ],
        )

    def test_generated_prices_stay_in_range_and_use_hundred_won_steps_when_possible(self):
        rng = np.random.default_rng(42)
        prices = [generate_mock_market_price(1500, rng) for _ in range(40)]

        self.assertTrue(all(1350 <= price <= 1650 for price in prices))
        self.assertTrue(all(price % 100 == 0 for price in prices))
        self.assertGreater(len(set(prices)), 1)

    def test_refresh_generation_always_changes_price_within_allowed_range(self):
        rng = np.random.default_rng(24)
        previous_price = 1500

        for _ in range(20):
            new_price = generate_mock_market_price(1500, rng, previous_price=previous_price)
            self.assertIsNotNone(new_price)
            self.assertNotEqual(new_price, previous_price)
            self.assertGreaterEqual(new_price, 1350)
            self.assertLessEqual(new_price, 1650)
            previous_price = new_price

    def test_refresh_generation_changes_prices_when_only_one_hundred_step_exists(self):
        new_price = generate_mock_market_price(500, np.random.default_rng(4), previous_price=500)

        self.assertNotEqual(new_price, 500)
        self.assertGreaterEqual(new_price, 450)
        self.assertLessEqual(new_price, 550)

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

    def test_recommended_price_migration_preserves_existing_analysis_rows(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE analysis_results (result_id INTEGER PRIMARY KEY, action_plans TEXT)"
            ))
            connection.execute(text(
                "INSERT INTO analysis_results (result_id, action_plans) VALUES (1, '기존 추천')"
            ))

        with patch("app.database.engine", engine):
            ensure_analysis_results_recommended_price_column()
            with engine.connect() as connection:
                row = connection.execute(text(
                    "SELECT action_plans, recommended_price FROM analysis_results WHERE result_id = 1"
                )).one()

        self.assertEqual(row.action_plans, "기존 추천")
        self.assertIsNone(row.recommended_price)
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
        mock_market_price = float(saved.mock_market_price)
        ai_result = {
            "status": "양호",
            "recommended_discount": 0,
            "recommended_price": mock_market_price,
            "comment": "시세 하한 적용",
        }
        with patch("app.routers.ai._diagnose", new=AsyncMock(return_value=ai_result)) as diagnose:
            diagnosis_response = asyncio.run(
                diagnose_saved_inventory(saved.item_id, SimpleNamespace(), session, User(user_id=1))
            )
        diagnosis_input = diagnose.await_args.args[0]
        self.assertEqual(diagnosis_input["current_market_price"], mock_market_price)
        self.assertEqual(diagnosis_response["recommended_price"], mock_market_price)

        inventory = list_inventory("", "", None, session, User(user_id=1))
        api_item = inventory["items"][0]

        self.assertEqual(float(saved.market_price), 1500)
        self.assertGreaterEqual(float(saved.mock_market_price), 1350)
        self.assertLessEqual(float(saved.mock_market_price), 1650)
        self.assertEqual(float(saved.mock_market_price) % 100, 0)
        self.assertEqual(api_item["selling_price"], 1500)
        self.assertEqual(api_item["mock_market_price"], float(saved.mock_market_price))
        self.assertEqual(api_item["recommended_price"], mock_market_price)
        export = get_export(None, session, User(user_id=1))
        self.assertEqual(export["items"][0]["mock_market_price"], float(saved.mock_market_price))
        self.assertEqual(export["items"][0]["recommended_price"], mock_market_price)

        refreshed = refresh_inventory_market_price(saved.item_id, session, User(user_id=1))
        self.assertNotEqual(refreshed["mock_market_price"], mock_market_price)
        self.assertIsNone(refreshed["recommended_price"])
        self.assertIn("다시 실행", refreshed["action_plans"])
        refreshed_inventory = list_inventory("", "", None, session, User(user_id=1))
        self.assertEqual(refreshed_inventory["items"][0]["mock_market_price"], refreshed["mock_market_price"])
        self.assertIsNone(refreshed_inventory["items"][0]["recommended_price"])

        session.close()
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
