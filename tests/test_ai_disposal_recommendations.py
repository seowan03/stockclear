import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.analysis import risk_grade_from_score
from app.llm import get_ai_strategy
from app.routers.ai import (
    _format_diagnosis_comment,
    _make_fallback_diagnosis,
    _make_strategy_context,
    _rule_based_strategy,
)


class AIDisposalRecommendationTests(unittest.TestCase):
    def _result(self, grade):
        return {
            "status": grade,
            "recommended_discount": 10,
            "recommended_price": 18000,
            "diagnosis_detail": {
                "source": "ai_explanation",
                "headline": f"테스트 상품 · {grade} · 위험점수 68점",
                "evidence": [{
                    "score_contribution": 1,
                    "metric": "보관 기간",
                    "value": 95,
                    "unit": "일",
                    "meaning": "보관 기간이 위험점수에 반영됐습니다.",
                    "next_check": "재고 수량과 입고일을 확인하세요.",
                }],
            },
        }

    def test_high_risk_grade_shows_two_disposal_actions(self):
        comment = _format_diagnosis_comment(self._result("장기"))

        self.assertIn("운영 중인 정리 판매나 기획전이 있다면 이 상품을 후보에 올려보세요.", comment)
        self.assertIn("판매 페이지의 판매 상태, 재고 수량, 상품 정보도 함께 점검해 보세요.", comment)
        self.assertNotIn("근거:", comment)
        self.assertNotIn("실행:", comment)
        self.assertNotIn("확인할 점:", comment)
        self.assertEqual(comment.count("재고 수량"), 1)
        self.assertIn("가격 참고값은 할인율 10%", comment)

    def test_normal_grade_does_not_recommend_disposal(self):
        comment = _format_diagnosis_comment(self._result("정상"))

        self.assertIn("현재 분석 기준에서 우선 처분을 권할 품목은 아닙니다.", comment)
        self.assertNotIn("정리 판매 후보 등록", comment)

    def test_rule_based_fallback_does_not_add_unconditional_check_items(self):
        context = _make_strategy_context({
            "item_id": 1,
            "product_name": "Smart Watch",
            "stock_qty": 80,
            "inventory_value": 2400000,
            "risk_grade": "악성",
            "risk_score": 80,
            "storage_days": 42,
            "days_to_sell": 120,
            "depreciation_rate": 20,
            "sales_speed": 0.7,
        })

        diagnosis = _make_fallback_diagnosis(context, "악성")

        self.assertTrue(all("next_check" not in item for item in diagnosis["evidence"]))

    def test_invalid_strategy_narrative_is_retried_once(self):
        context = _make_strategy_context({
            "item_id": 1,
            "product_name": "Smart Watch",
            "stock_qty": 80,
            "purchase_price": 30000,
            "selling_price": 18000,
            "storage_days": 42,
            "days_to_sell": 120,
            "depreciation_rate": 20,
            "sales_speed": 0.7,
            "risk_grade": "악성",
            "risk_score": 80,
        })
        payloads = [
            {"evidence": [{
                "metric": "보관 기간",
                "evidence_ref": "analysis.risk_score_components.storage_days",
                "meaning": "Smart Watch의 보관 기간이 위험점수에 반영됐습니다.",
                "next_check": "입고 정보와 재고 입력값을 확인하세요.",
            }]},
            {"evidence": [{
                "metric": "보관 기간",
                "evidence_ref": "analysis.risk_score_components.storage_days",
                "meaning": "보관 기간이 위험점수에 반영된 지표입니다.",
                "next_check": "입고 정보와 재고 입력값을 확인하세요.",
            }]},
        ]
        responses = [
            SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)),
            )])
            for payload in payloads
        ]
        calls = []

        def create_response(**kwargs):
            calls.append(kwargs)
            return responses[len(calls) - 1]

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=create_response,
        )))

        with patch("app.llm._get_client", return_value=client):
            result = get_ai_strategy(context)

        self.assertEqual(len(calls), 2)
        self.assertEqual(result["evidence"][0]["meaning"], "보관 기간이 위험점수에 반영된 지표입니다.")
        self.assertEqual(
            [message["role"] for message in calls[1]["messages"]],
            ["system", "system", "user"],
        )
        self.assertIn("상품명을 직접 포함할 수 없습니다", calls[1]["messages"][1]["content"])

    def test_rule_based_strategy_uses_shared_score_grade_thresholds(self):
        self.assertEqual(risk_grade_from_score(24.9), "정상")
        self.assertEqual(risk_grade_from_score(25), "주의")
        self.assertEqual(risk_grade_from_score(45), "장기")
        self.assertEqual(risk_grade_from_score(70), "악성")

        recommendation = _rule_based_strategy({
            "storage_days": 60,
            "days_to_sell": 0,
            "depreciation_rate": 0,
            "stock_qty": 20,
            "sales_speed": 1,
        })
        self.assertEqual(recommendation["status"], "주의")


if __name__ == "__main__":
    unittest.main()