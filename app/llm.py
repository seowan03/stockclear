import json
import logging
from typing import Any, Literal

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from app.config import OPENAI_API_KEY

logger = logging.getLogger(__name__)


class AIStrategy(BaseModel):
    status: Literal["정상", "주의", "장기", "악성"]
    recommended_discount: float = Field(ge=0, le=100)
    comment: str


def _get_client(timeout: float = 20.0, max_retries: int = 1) -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=OPENAI_API_KEY, timeout=timeout, max_retries=max_retries)


def get_ai_strategy(product_data: dict[str, Any]) -> dict[str, Any]:
    """
    재고 데이터를 받아 GPT-4o-mini를 통해 처방전을 반환하는 함수
    """
    prompt = f"""
    당신은 직매입 중심의 중소 규모 이커머스 셀러를 위한 전문 재고 컨설턴트입니다.
    셀러가 미리 사입해 둔 재고가 창고에 묶여 현금 흐름이 막히는 것을 방지하고, 원가 방어 및 창고 회전율을 높일 수 있는 실전 처방전을 내려주세요

    [재고 데이터]
    - 상품명: {product_data.get('product_name','알 수 없음')}
    - 보관 기간: {product_data.get('storage_days', 0)}일
    - 현재 재고량: {product_data.get('stock_qty', 0)}개
    - 원가(사입가): {product_data.get('purchase_price', 0)}원
    - 현재 기준 시세: {product_data.get('current_market_price', product_data.get('mock_market_price', product_data.get('selling_price', 0)))}원
    - 현재 기준 시세: {product_data.get('current_market_price', product_data.get('mock_market_price', product_data.get('selling_price', 0)))}원

    반드시 아래 JSON 형식으로만 답변해주세요. 다른 부가 설명 텍스트는 절대 포함하지 마세요.
    {{
        "status": "정상 / 주의 / 장기 / 악성 중 택1",
        "recommended_discount": 30,
        "comment": "보관 기간이 길어 회전율이 낮으므로 30% 일괄 할인을 권장합니다"
    }}
    """

    try:
        response = _get_client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "당신은 이커머스 직매입 재고 관리 전문가입니다. 정확한 JSON 형식으로만 응답합니다.",
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )

        result_content = response.choices[0].message.content
        if not result_content:
            raise ValueError("OpenAI returned an empty response")

        result = AIStrategy.model_validate(json.loads(result_content))
        return result.model_dump()

    except (json.JSONDecodeError, ValidationError, RuntimeError, ValueError):
        logger.exception("AI strategy response validation failed")
        return {
            "status": "분석 오류",
            "recommended_discount": 0,
            "comment": "AI 분석을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.",
        }
    except Exception:
        logger.exception("AI strategy request failed")
        return {
            "status": "분석 오류",
            "recommended_discount": 0,
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


