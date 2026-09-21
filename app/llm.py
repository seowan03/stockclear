import json
import logging
import os
from typing import Any

from openai import OpenAI
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

load_dotenv()
<<<<<<< HEAD
=======

# 운영 환경에서만 키 누락을 즉시 차단하고, 개발 환경에서는 키 없이도 서버를 실행할 수 있게 허용한다.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY and os.getenv("ENV", "development") == "production":
    raise RuntimeError("OPENAI_API_KEY 환경 변수가 설정되지 않았습니다. .env 파일을 확인하세요.")
if not OPENAI_API_KEY:
    print("⚠️  OPENAI_API_KEY가 설정되지 않았습니다. AI 진단 API는 호출 시 오류를 반환합니다.")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
>>>>>>> 8cada1cbd3764bfb48bb416accf1cd0e9b5ddac6

logger = logging.getLogger(__name__)


class AIStrategy(BaseModel):
    status: str
    recommended_discount: float = Field(ge=0, le=100)
    comment: str


def _get_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=api_key, timeout=20.0, max_retries=1)


def get_ai_strategy(product_data: dict[str, Any]) -> dict[str, Any]:
    """
    재고 데이터를 받아 GPT-4o-mini를 통해 처방전을 반환하는 함수
    """
    if client is None:
        return {
            "status": "분석 오류",
            "recommended_discount": 0,
            "comment": "OPENAI_API_KEY가 설정되지 않아 AI 분석을 수행할 수 없습니다.",
        }

    prompt = f"""
    당신은 직매입 중심의 중소 규모 이커머스 셀러를 위한 전문 재고 컨설턴트입니다.
    셀러가 미리 사입해 둔 재고가 창고에 묶여 현금 흐름이 막히는 것을 방지하고, 원가 방어 및 창고 회전율을 높일 수 있는 실전 처방전을 내려주세요

    [재고 데이터]
    - 상품명: {product_data.get('product_name','알 수 없음')}
    - 보관 기간: {product_data.get('storage_days', 0)}일
    - 현재 재고량: {product_data.get('stock_qty', 0)}개
    - 원가(사입가): {product_data.get('purchase_price', 0)}원

    반드시 아래 JSON 형식으로만 답변해주세요. 다른 부가 설명 텍스트는 절대 포함하지 마세요.
    {{
        "status": "악성재고 위험 / 주의 / 양호 중 택1",
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


