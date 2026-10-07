import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.llm import get_ai_strategy


class AIStrategyResponseTests(unittest.TestCase):
    def _client_with_response(self, payload):
        response = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)),
            )],
        )
        return SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: response),
            ),
        )

    def test_english_metric_keys_from_model_are_normalized(self):
        payload = {
            "evidence": [
                {"metric": "storage_days", "meaning": "보관 기간을 확인합니다."},
                {"metric": "days_to_sell", "meaning": "소진 기간을 확인합니다."},
                {
                    "metric": "sales_velocity_uploaded_basis",
                    "meaning": "업로드 판매 속도 기준입니다.",
                },
            ],
            "checks": [{
                "priority": 1,
                "action": "실제 재고를 확인합니다.",
                "reason": "수량은 업로드 기준입니다.",
            }],
            "next_review": "확인 후 다시 검토합니다.",
        }

        with patch("app.llm._get_client", return_value=self._client_with_response(payload)):
            result = get_ai_strategy({"analysis": {"storage_days": 90}})

        self.assertEqual(
            [entry["metric"] for entry in result["evidence"]],
            ["보관 기간", "예상 소진 기간", "업로드 판매 속도"],
        )
        self.assertEqual(len(result), 1)

    def test_unknown_metric_still_fails_validation_safely(self):
        payload = {
            "evidence": [{"metric": "made_up_metric", "meaning": "설명"}],
            "checks": [{"priority": 1, "action": "확인", "reason": "근거"}],
            "next_review": "재검토",
        }

        with patch("app.llm._get_client", return_value=self._client_with_response(payload)):
            result = get_ai_strategy({})

        self.assertEqual(result["status"], "분석 오류")


if __name__ == "__main__":
    unittest.main()