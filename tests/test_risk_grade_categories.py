import unittest
from unittest.mock import patch

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

import app.database as database
from app.routers.ai import _rule_based_strategy
from app.analysis import _classify_risk
from app.models import AnalysisResult


class RiskGradeCategoryTests(unittest.TestCase):
    def test_score_thresholds_return_only_canonical_grades(self):
        inventory = pd.DataFrame({
            "보관기간": [0, 30, 60, 90],
            "예상소진기간": [0, 70, 110, 180],
            "감가율": [0, 0, 0, 0],
        })

        _, grades = _classify_risk(inventory)

        self.assertEqual(list(grades), ["정상", "주의", "장기", "악성"])
        self.assertEqual(set(grades), {"정상", "주의", "장기", "악성"})

    def test_ai_fallback_uses_only_canonical_grades(self):
        cases = [
            ({"storage_days": 0, "days_to_sell": 0, "stock_qty": 5, "sales_speed": 1}, "정상"),
            ({"storage_days": 45, "days_to_sell": 0, "stock_qty": 5, "sales_speed": 1}, "주의"),
            ({"storage_days": 60, "days_to_sell": 0, "stock_qty": 5, "sales_speed": 1}, "장기"),
            ({"storage_days": 90, "days_to_sell": 0, "stock_qty": 5, "sales_speed": 1}, "악성"),
        ]

        for data, expected_grade in cases:
            with self.subTest(expected_grade=expected_grade):
                result = _rule_based_strategy(data)
                self.assertEqual(result["status"], expected_grade)
                self.assertIn(result["status"], {"정상", "주의", "장기", "악성"})

    def test_legacy_database_grades_are_normalized_by_score(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        try:
            database.Base.metadata.create_all(engine)
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO analysis_results (item_id, risk_grade, final_score) "
                    "VALUES (1, '위험', 55), (2, '처분 권장', 75), (3, '미분류', 30)"
                ))

            with patch.object(database, "engine", engine):
                database.ensure_analysis_risk_grade_values()

            with engine.connect() as connection:
                grades = connection.execute(text(
                    "SELECT risk_grade FROM analysis_results ORDER BY item_id"
                )).scalars().all()

            self.assertEqual(grades, ["장기", "악성", "주의"])
            self.assertTrue(set(grades).issubset({"정상", "주의", "장기", "악성"}))
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()