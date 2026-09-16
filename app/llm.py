import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def get_ai_startegy(product_data: dict) -> dict:
    """
    재고 데이터를 받아 GPT-4o-mini를 통해 처방전을 반환하는 함수
    """
    prompt = f"""
    당신은 직매입 중심의 중소 규모 이커머스 셀러를 위한 전문 재고 컨설턴트입니다.
    셀러가 미리 사입해 둔 재고가 창고에 묶여 현금 흐름이 막히는 것을 방지하고, 원가 방어 및 창고 회전율을 높일 수 있는 실전 처방전을 내려주세요

    [재고 데이터]
    - 상품명: {product_data.get('product_name','알 수 없음')}
    - 보관 기간: {product_data.get('storage_day', 0)}일
    - 현재 재고량: {product_data.get('stock_qty', 0)}개
    - 원가(사입가): {product_data.get('cost_price', 0)}원

    반드시 아래 JSON 형식으로만 답변해주세요. 다른 부가 설명 텍스트는 절대 포함하지 마세요.
    {{
        "status": "악성재고 위험 / 주의 / 양호 중 택1",
        "recommended_discount": 30,
        "comment": "보관 기간이 길어 회전율이 낮으므로 30% 일괄 할인을 권장합니다"
    }}
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role":"system","content": "당신은 이커머스 직매입 재고 관리 전문가입니다. 정확한 JSON 형식으로만 응답합니다."},
                {"role":"user","content":prompt}
            ],
            response_format={"type:json_object"}
        )

        result_content = response.choices[0].messages
        return json.loads(result_content)

    except Exception as e:
        return {
            "status": "분석 오류",
            "recommended_discount": 0,
            "comment": f"AI 분석 중 오류 발생: {str(e)}"
        }