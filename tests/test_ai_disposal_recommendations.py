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

    def test_generic_storage_metric_definition_is_omitted(self):
        result = self._result("악성")
        result["diagnosis_detail"]["evidence"][0]["meaning"] = "보관 중인 재고의 기간을 나타냅니다."

        comment = _format_diagnosis_comment(result)

        self.assertNotIn("보관 중인 재고의 기간을 나타냅니다.", comment)
        self.assertIn("위험점수에는 보관 기간 95일이 반영됐습니다.", comment)

    def test_placeholder_meaning_is_not_shown_as_ai_explanation(self):
        result = self._result("악성")
        result["diagnosis_detail"]["evidence"][0]["meaning"] = "보관 기간의 서버 저장 분석값입니다."

        comment = _format_diagnosis_comment(result)

        self.assertNotIn("서버 저장 분석값", comment)
        self.assertIn("위험점수에는 보관 기간 95일이 반영됐습니다.", comment)

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
            }]},
            {"evidence": [{
                "metric": "보관 기간",
                "evidence_ref": "analysis.risk_score_components.storage_days",
                "meaning": "보관 기간이 위험점수에 반영된 지표입니다.",
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

    def test_item_strategy_does_not_require_unused_next_check(self):
        context = _make_strategy_context({
            "item_id": 1,
            "product_name": "Mini Drone",
            "stock_qty": 80,
            "purchase_price": 50000,
            "selling_price": 25000,
            "storage_days": 41,
            "days_to_sell": 153,
            "depreciation_rate": 50,
            "sales_speed": 0.8,
            "risk_grade": "악성",
            "risk_score": 73.8,
        })
        payload = {"evidence": [{
            "metric": "보관 기간",
            "evidence_ref": "analysis.risk_score_components.storage_days",
            "meaning": "보관 기간이 길어 재고 회전이 늦어질 가능성을 살펴볼 필요가 있습니다.",
        }]}
        response = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)),
        )])
        calls = []
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **kwargs: calls.append(kwargs) or response,
        )))

        with patch("app.llm._get_client", return_value=client):
            result = get_ai_strategy(context)

        self.assertEqual(len(calls), 1)
        self.assertNotIn("next_check", result["evidence"][0])

    def test_generic_metric_definitions_are_retried(self):
        context = _make_strategy_context({
            "item_id": 1,
            "product_name": "Mini Drone",
            "stock_qty": 80,
            "purchase_price": 50000,
            "selling_price": 25000,
            "storage_days": 41,
            "days_to_sell": 153,
            "depreciation_rate": 50,
            "sales_speed": 0.8,
            "risk_grade": "악성",
            "risk_score": 73.8,
        })
        metrics = [
            (
                "보관 기간",
                "analysis.risk_score_components.storage_days",
                "보관 기간은 재고의 유지 시간을 나타내며, 이 지표는 위험 점수에 영향을 미쳐 위험도를 평가하는 데 사용된다.",
                "보관 기간이 길어 위험점수 기여가 커졌습니다.",
            ),
            (
                "예상 소진 기간",
                "analysis.risk_score_components.days_to_sell",
                "예상 소진 기간은 현재 재고가 얼마나 오랫동안 유지될지를 예측하며, 이 정보는 위험 점수 반영에 중요한 역할을 한다.",
                "예상 소진 기간이 길어 재고 회전 위험에 반영됐습니다.",
            ),
            (
                "원가 대비 판매가 차이",
                "analysis.risk_score_components.depreciation_rate",
                "원가 대비 판매가 차이는 재고의 경제적 가치를 평가하는 데 사용되며, 이 수치는 위험 점수에 포함되어 전체적인 위험도를 측정하는 데 기여한다.",
                "판매가가 원가보다 낮은 상태가 위험점수에 반영됐습니다.",
            ),
        ]
        payloads = [
            {"evidence": [
                {
                    "metric": metric,
                    "evidence_ref": evidence_ref,
                    "meaning": meaning,
                }
                for metric, evidence_ref, meaning in meanings
            ]}
            for meanings in ([entry[:3] for entry in metrics], [
                (metric, evidence_ref, corrected_meaning)
                for metric, evidence_ref, _generic_meaning, corrected_meaning in metrics
            ])
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
        self.assertEqual(
            [entry["meaning"] for entry in result["evidence"]],
            [entry[3] for entry in metrics],
        )
        self.assertIn("지표 정의나 위험점수 반영을 일반적으로 반복했습니다", calls[1]["messages"][1]["content"])
        self.assertIn("사전적 정의를 반복하지 말고", calls[1]["messages"][1]["content"])

    def test_generic_score_restatements_are_retried(self):
        context = _make_strategy_context({
            "item_id": 1,
            "product_name": "Mini Drone",
            "stock_qty": 80,
            "purchase_price": 50000,
            "selling_price": 25000,
            "storage_days": 41,
            "days_to_sell": 153,
            "depreciation_rate": 50,
            "sales_speed": 0.8,
            "risk_grade": "악성",
            "risk_score": 73.8,
        })
        entries = [
            (
                "보관 기간",
                "analysis.risk_score_components.storage_days",
                "상품이 현재 재고로 보관되어 있던 기간입니다.",
                "오랜 기간 재고가 보관돼 재고 회전이 늦어질 가능성을 우선 살펴볼 필요가 있습니다.",
            ),
            (
                "예상 소진 기간",
                "analysis.risk_score_components.days_to_sell",
                "현재 재고가 예상 소진되는 기간입니다.",
                "현재 재고가 판매 속도에 비해 많아 소진까지 긴 시간이 걸릴 수 있습니다.",
            ),
            (
                "원가 대비 판매가 차이",
                "analysis.risk_score_components.depreciation_rate",
                "상품의 원가와 판매가 간의 차이를 나타내는 비율입니다.",
                "판매가가 원가보다 낮아 원가 회수에 불리한 상태입니다.",
            ),
        ]
        payloads = [
            {"evidence": [
                {
                    "metric": metric,
                    "evidence_ref": evidence_ref,
                    "meaning": meaning,
                }
                for metric, evidence_ref, meaning, _ in entries
            ]},
            {"evidence": [
                {
                    "metric": metric,
                    "evidence_ref": evidence_ref,
                    "meaning": corrected_meaning,
                }
                for metric, evidence_ref, _meaning, corrected_meaning in entries
            ]},
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
        self.assertEqual(
            [entry["meaning"] for entry in result["evidence"]],
            [entry[3] for entry in entries],
        )
        self.assertIn("점수에 반영된다는 일반 문구도 반복하지 말고", calls[1]["messages"][1]["content"])

    def test_repeated_generic_metric_definitions_do_not_reach_fallback_comment(self):
        context = _make_strategy_context({
            "item_id": 1,
            "product_name": "Mini Drone",
            "stock_qty": 80,
            "purchase_price": 50000,
            "selling_price": 25000,
            "storage_days": 41,
            "days_to_sell": 153,
            "depreciation_rate": 50,
            "sales_speed": 0.8,
            "risk_grade": "악성",
            "risk_score": 73.8,
        })
        generic_meanings = [
            "상품이 현재 재고로 보관되어 있던 기간입니다.",
            "현재 재고가 예상 소진되는 기간입니다.",
            "상품의 원가와 판매가 간의 차이를 나타내는 비율입니다.",
        ]
        metrics = [
            ("보관 기간", "analysis.risk_score_components.storage_days"),
            ("예상 소진 기간", "analysis.risk_score_components.days_to_sell"),
            ("원가 대비 판매가 차이", "analysis.risk_score_components.depreciation_rate"),
        ]
        payload = {"evidence": [
            {
                "metric": metric,
                "evidence_ref": evidence_ref,
                "meaning": meaning,
            }
            for (metric, evidence_ref), meaning in zip(metrics, generic_meanings)
        ]}
        responses = [
            SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)),
            )])
            for _ in range(2)
        ]
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **_kwargs: responses.pop(0),
        )))

        with patch("app.llm._get_client", return_value=client):
            ai_result = get_ai_strategy(context)

        fallback = _make_fallback_diagnosis(context, "악성")
        comment = _format_diagnosis_comment({
            "status": "악성",
            "recommended_discount": 30,
            "recommended_price": 25000,
            "diagnosis_detail": fallback,
        })

        self.assertEqual(ai_result["status"], "분석 오류")
        self.assertTrue(all(meaning not in comment for meaning in generic_meanings))
        self.assertIn("위험점수에는", comment)

    def test_generic_entry_is_dropped_when_other_evidence_is_valid(self):
        context = _make_strategy_context({
            "item_id": 1,
            "product_name": "Mini Drone",
            "stock_qty": 80,
            "purchase_price": 50000,
            "selling_price": 25000,
            "storage_days": 41,
            "days_to_sell": 153,
            "depreciation_rate": 50,
            "sales_speed": 0.8,
            "risk_grade": "악성",
            "risk_score": 73.8,
        })
        payload = {"evidence": [
            {
                "metric": "보관 기간",
                "evidence_ref": "analysis.risk_score_components.storage_days",
                "meaning": "보관 기간이 길어 위험점수에 반영되어 위험도가 높아졌습니다.",
            },
            {
                "metric": "원가 대비 판매가 차이",
                "evidence_ref": "analysis.risk_score_components.depreciation_rate",
                "meaning": "판매가가 원가보다 낮아 원가 회수에 불리한 상태입니다.",
            },
        ]}
        response = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)),
        )])
        calls = []
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **kwargs: calls.append(kwargs) or response,
        )))

        with patch("app.llm._get_client", return_value=client):
            result = get_ai_strategy(context)

        self.assertEqual(len(calls), 1)
        self.assertEqual(
            [entry["metric"] for entry in result["evidence"]],
            ["원가 대비 판매가 차이"],
        )

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