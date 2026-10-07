import asyncio
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as database
from app.database import Base
from app.models import AnalysisResult, RawInventory, User
from app.routers.ai import diagnose_saved_inventory


class AIDiagnosisCacheTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.session.add_all([
            User(user_id=7, username="Cache User", email="cache@example.test", password_hash="x"),
            RawInventory(
                item_id=17,
                user_id=7,
                product_name="Cache Item",
                stock_qty=8,
                purchase_price=100,
                market_price=120,
                mock_market_price=110,
                inbound_date=date(2026, 9, 1),
                sales_qty=4,
                is_deleted=False,
            ),
            AnalysisResult(
                item_id=17,
                sales_velocity=0.25,
                aging_days=70,
                days_to_sell=90,
                risk_grade="장기",
                inventory_amount=800,
                final_score=46.1,
                fluctuation_rate=-20,
                updated_at=datetime(2026, 10, 7, 12),
            ),
        ])
        self.session.commit()
        self.request = SimpleNamespace(
            headers={},
            client=SimpleNamespace(host="diagnosis-cache-test"),
        )

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def _ai_response(self, meaning):
        return {
            "evidence": [
                {"metric": "보관 기간", "meaning": meaning},
                {"metric": "예상 소진 기간", "meaning": "업로드 기준 소진 기간입니다."},
            ],
            "checks": [{
                "priority": 1,
                "action": "실제 판매 가능 재고를 확인합니다.",
                "reason": "현재 수량은 업로드 기준입니다.",
            }],
            "next_review": "실제 수량을 확인한 뒤 다시 검토합니다.",
        }

    def _diagnose(self):
        return asyncio.run(diagnose_saved_inventory(
            17,
            self.request,
            self.session,
            User(user_id=7),
        ))

    def test_same_inputs_reuse_response_and_changed_inputs_call_ai_again(self):
        with patch(
            "app.routers.ai.get_ai_strategy",
            side_effect=[self._ai_response("첫 진단 설명"), self._ai_response("변경 후 설명")],
        ) as generate:
            first = self._diagnose()
            repeated = self._diagnose()

            self.assertFalse(first["cache_hit"])
            self.assertTrue(repeated["cache_hit"])
            self.assertEqual(repeated["judgment"], first["judgment"])
            generate.assert_called_once()

            item = self.session.get(RawInventory, 17)
            item.stock_qty = 9
            self.session.commit()
            changed = self._diagnose()

        self.assertFalse(changed["cache_hit"])
        self.assertIn("변경 후 설명", changed["judgment"])
        self.assertEqual(generate.call_count, 2)

    def test_old_format_cache_is_regenerated_after_cache_version_change(self):
        with patch("app.routers.ai.DIAGNOSIS_CACHE_VERSION", "v2"):
            with patch(
                "app.routers.ai.get_ai_strategy",
                return_value=self._ai_response("이전 출력 형식"),
            ):
                old_result = self._diagnose()
        self.assertFalse(old_result["cache_hit"])

        with patch(
            "app.routers.ai.get_ai_strategy",
            return_value=self._ai_response("새 출력 형식"),
        ) as generate:
            refreshed = self._diagnose()

        self.assertFalse(refreshed["cache_hit"])
        self.assertIn("새 출력 형식", refreshed["judgment"])
        generate.assert_called_once()

    def test_cache_columns_migrate_existing_analysis_table_without_data_loss(self):
        engine = create_engine("sqlite:///:memory:")
        try:
            with engine.begin() as connection:
                connection.execute(text(
                    "CREATE TABLE analysis_results (result_id INTEGER PRIMARY KEY, ai_diagnosis TEXT)"
                ))
                connection.execute(text(
                    "INSERT INTO analysis_results (result_id, ai_diagnosis) VALUES (1, '기존 진단')"
                ))

            with patch.object(database, "engine", engine):
                database.ensure_analysis_results_diagnosis_cache_columns()
                database.ensure_analysis_results_diagnosis_cache_columns()

            columns = {column["name"] for column in inspect(engine).get_columns("analysis_results")}
            self.assertIn("diagnosis_input_hash", columns)
            self.assertIn("diagnosis_cache", columns)
            with engine.connect() as connection:
                row = connection.execute(text(
                    "SELECT ai_diagnosis, diagnosis_input_hash, diagnosis_cache "
                    "FROM analysis_results WHERE result_id = 1"
                )).one()
            self.assertEqual(row.ai_diagnosis, "기존 진단")
            self.assertIsNone(row.diagnosis_input_hash)
            self.assertIsNone(row.diagnosis_cache)
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
