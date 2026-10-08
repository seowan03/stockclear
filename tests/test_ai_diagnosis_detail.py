import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.routers.ai import _apply_price_floors, _diagnose


class AIDiagnosisDetailTests(unittest.TestCase):
    def setUp(self):
        self.product_data = {
            "item_id": 17,
            "product_name": "Widget",
            "stock_qty": 8,
            "purchase_price": 100,
            "selling_price": 120,
            "mock_market_price": 110,
            "current_market_price": 110,
            "inventory_value": 800,
            "sales_qty": 4,
            "sales_speed": 0.25,
            "storage_days": 90,
            "days_to_sell": 120,
            "depreciation_rate": -20,
            "risk_grade": "장기",
            "risk_score": 60,
            "risk_score_components": {
                "storage_score": 40.0,
                "turnover_score": 20.0,
                "depreciation_score": 0.0,
            },
            "analysis_as_of": "2026-10-07T12:00:00",
            "market_price_source": "mock",
        }
        self.ai_response = {
            "evidence": [
                {"metric": "보관 기간", "meaning": "보관 기간 점수 기여가 큽니다."},
                {"metric": "예상 소진 기간", "meaning": "업로드 판매 속도가 유지된다는 가정의 기준값입니다."},
                {"metric": "원가 대비 판매가 차이", "meaning": "원가와 업로드 판매가 사이의 차이입니다."},
            ],
        }
        self.request = SimpleNamespace(
            headers={},
            client=SimpleNamespace(host="diagnosis-test"),
        )

    def test_server_owns_grade_discount_and_numeric_evidence(self):
        with patch("app.routers.ai.get_ai_strategy", return_value={
            **self.ai_response,
            "status": "악성",
            "recommended_discount": 70,
        }) as generate:
            result = asyncio.run(_diagnose(self.product_data, 8301, self.request))

        self.assertEqual(result["status"], "장기")
        self.assertEqual(result["recommended_discount"], 10)
        self.assertEqual(result["recommendation_source"], "rule_based_reference")
        self.assertEqual(result["diagnosis_detail"]["source"], "ai_explanation")
        evidence = result["diagnosis_detail"]["evidence"]
        self.assertEqual([item["value"] for item in evidence], [90, 0.25, 120, -20])
        self.assertEqual([item["score_contribution"] for item in evidence], [40.0, None, 20.0, 0.0])
        self.assertTrue(result["diagnosis_detail"]["headline"].startswith("Widget은 서버 분석 기준 장기 등급"))
        self.assertTrue(result["comment"].startswith("AI 설명 · 우선 확인 대상"))
        self.assertIn("주요 원인은 보관 기간 90일(40/40점)", result["comment"])
        self.assertIn("AI 해석: 보관 기간 점수 기여가 큽니다.", result["comment"])
        self.assertIn("업로드 기준 판매 속도는 0.25개/일입니다.", result["comment"])
        self.assertNotIn("확인할 항목", result["comment"])
        self.assertNotIn("데이터 한계", result["comment"])
        self.assertIn("규칙 기반 참고 할인율은 10%", result["comment"])

        context = generate.call_args.args[0]
        self.assertEqual(context["pricing"]["market_price"], None)
        self.assertEqual(context["pricing"]["market_price_source"], "mock")
        self.assertNotIn("current_market_price", context)

    def test_ai_failure_returns_same_detail_shape_with_server_fallback(self):
        with patch("app.routers.ai.get_ai_strategy", return_value={"status": "분석 오류"}):
            result = asyncio.run(_diagnose(self.product_data, 8302, self.request))

        detail = result["diagnosis_detail"]
        self.assertEqual(detail["source"], "rule_based_fallback")
        self.assertEqual(result["status"], "장기")
        self.assertEqual(result["recommended_discount"], 10)
        self.assertTrue(detail["evidence"])
        self.assertTrue(result["comment"].startswith("규칙 기반 진단 · 우선 확인 대상"))
        self.assertNotIn("확인할 항목", result["comment"])
        self.assertNotIn("데이터 한계", result["comment"])

    def test_price_floor_does_not_require_a_market_quote(self):
        result = _apply_price_floors(
            {"recommended_discount": 10},
            {"selling_price": 120, "purchase_price": 100},
        )

        self.assertEqual(result["recommended_discount"], 10)
        self.assertEqual(result["recommended_price"], 108)


if __name__ == "__main__":
    unittest.main()
