import json
import logging
from typing import Any, Literal

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from app.config import OPENAI_API_KEY

logger = logging.getLogger(__name__)

STRATEGY_METRIC_ALIASES = {
    "storage_days": "보관 기간",
    "sales_speed": "업로드 판매 속도",
    "sales_velocity_uploaded_basis": "업로드 판매 속도",
    "days_to_sell": "예상 소진 기간",
    "depreciation_rate": "원가 대비 판매가 차이",
    "fluctuation_rate": "원가 대비 판매가 차이",
}


class AIStrategy(BaseModel):
    evidence: list["AIStrategyEvidence"] = Field(max_length=4)


class AIStrategyEvidence(BaseModel):
    metric: Literal["보관 기간", "업로드 판매 속도", "예상 소진 기간", "원가 대비 판매가 차이"]
    meaning: str = Field(min_length=1, max_length=240)


def _get_client(timeout: float = 20.0, max_retries: int = 1) -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=OPENAI_API_KEY, timeout=timeout, max_retries=max_retries)


def get_ai_strategy(product_data: dict[str, Any]) -> dict[str, Any]:
    """Return structured explanations only; the server owns risk and pricing decisions."""
    prompt = json.dumps(product_data, ensure_ascii=False)

    try:
        response = _get_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "당신은 품목별 재고 진단 설명을 작성합니다. 사용자 메시지는 서버가 만든 "
                        "정규화 입력입니다. 입력된 위험등급과 위험점수는 서버 확정값이므로 변경하지 말고, "
                        "등급이나 할인율을 새로 결정하지 마세요. 보관 기간, 업로드 판매 속도, "
                        "예상 소진 기간, 원가 대비 판매가 차이 중 입력에 있는 항목만 설명하세요. "
                        "숫자·가격·상품 속성·원인·판매 추세를 입력에 없는 형태로 만들지 마세요. "
                        "업로드 누계 판매량을 실거래 추세로, 모의 시세를 시장 가격으로 표현하지 마세요. "
                        "실제 주문 이력이나 비용 자료가 없으면 할인 효과, 이익, 절감액, 발주량을 "
                        "추정하거나 지시하지 마세요. 다음 JSON 필드만 정확히 반환하세요: "
                        "evidence[{metric,meaning}]. "
                        "evidence.metric은 반드시 다음 네 문자열 중 하나를 그대로 사용하세요: "
                        "'보관 기간', '업로드 판매 속도', '예상 소진 기간', '원가 대비 판매가 차이'. "
                        "입력 JSON의 영문 키(storage_days, sales_velocity_uploaded_basis, days_to_sell, "
                        "depreciation_rate)를 metric 값으로 반환하지 마세요. 예시: "
                        "{\"evidence\":[{\"metric\":\"보관 기간\",\"meaning\":\"보관 기간이 길어 소진 상태를 확인할 필요가 있습니다.\"}]}. "
                        "지표의 숫자 값은 반환하지 마세요."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=1000,
        )

        result_content = response.choices[0].message.content
        if not result_content:
            raise ValueError("OpenAI returned an empty response")

        result_data = json.loads(result_content)
        if isinstance(result_data, dict) and isinstance(result_data.get("evidence"), list):
            for evidence in result_data["evidence"]:
                if isinstance(evidence, dict):
                    metric = evidence.get("metric")
                    evidence["metric"] = STRATEGY_METRIC_ALIASES.get(metric, metric)

        result = AIStrategy.model_validate(result_data)
        return result.model_dump()

    except (json.JSONDecodeError, ValidationError, RuntimeError, ValueError):
        logger.exception("AI strategy response validation failed")
        return {
            "status": "분석 오류",
            "comment": "AI 분석을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.",
        }
    except Exception:
        logger.exception("AI strategy request failed")
        return {
            "status": "분석 오류",
            "comment": "AI 분석 중 일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
        }


def get_upload_diagnosis_summary(summary_data: dict[str, Any]) -> str:
    """Generate a Korean inventory report grounded in the supplied account data."""
    response = _get_client(timeout=12.0, max_retries=0).chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "당신은 재고 분석 보고서 작성자입니다. 입력된 실제 계정 데이터만 근거로 "
                    "한국어 보고서를 작성하고 다음 제목을 사용하세요: 전체 현황, 등급 분포, "
                    "우선 확인 품목, 개선 조치, 데이터 한계. 각 조치는 근거, 확인 행동, "
                    "다음 판단 순서로 작성하세요. 입력에 없는 상품명, 수치, 원인, 판매 추세를 "
                    "만들지 마세요. 품목명과 수치는 입력된 경우에만 언급하고, 품목이 없으면 "
                    "우선 확인 품목이 없다고 쓰세요. 재고금액은 원가 기준 자산으로만 설명하세요. "
                    "일별 판매량은 시연 데이터일 수 있으므로 data_quality를 따르며 실거래처럼 "
                    "표현하지 마세요. 실제 주문 이력이나 리드타임이 없으면 추세, 할인 효과, "
                    "이익, 절감액, 결품 확률, 발주량을 추정하거나 지시하지 마세요. "
                    "입력에 없는 등급·비중·금액은 생략하고, 전체 품목이 0개면 분석 대상이 없다고 안내하세요."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(summary_data, ensure_ascii=False),
            },
        ],
        max_tokens=1000,
    )
    summary = response.choices[0].message.content
    if not summary or not summary.strip():
        raise ValueError("OpenAI returned an empty upload summary")
    return summary.strip()[:3000]


