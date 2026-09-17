from collections import Counter

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from app.models import RawInventory
from app.schemas import InventoryItem

router = APIRouter()


# 현재 로그인한 사용자의 업로드 묶음별 데이터와 현재 업로드 데이터를 비교해 같은 batch_id를 찾음
def find_duplicate_upload_batch(db: Session, user_id: int, upload_signature):
    existing_items = (
        db.query(RawInventory)
        .filter(
            RawInventory.user_id == user_id,
            RawInventory.upload_batch_id.isnot(None),
        )
        .order_by(RawInventory.upload_batch_id, RawInventory.item_id)
        .all()
    )

    batch_signatures = {}
    for item in existing_items:
        # 같은 upload_batch_id끼리 행 데이터를 모아 하나의 업로드 파일 내용처럼 비교
        batch_signatures.setdefault(item.upload_batch_id, Counter()).update([
            (
                item.product_name,
                item.stock_qty,
                item.purchase_price,
                item.inbound_date,
                item.market_price,
                item.sales_qty,
            )
        ])

    for upload_batch_id, existing_signature in batch_signatures.items():
        if existing_signature == upload_signature:
            return upload_batch_id

    return None


# 중복 업로드가 확인되면 main.py의 업로드 흐름을 중단시키는 예외 발생
def raise_if_duplicate_upload(db: Session, user_id: int, upload_signature):
    duplicate_batch_id = find_duplicate_upload_batch(db, user_id, upload_signature)
    if duplicate_batch_id:
        raise HTTPException(
            status_code=409,
            detail=f"이미 같은 내용의 엑셀 데이터가 업로드되어 있습니다. batch_id: {duplicate_batch_id}"
        )

# --- AI 처방전 진단 API ---
@router.post("/api/ai-diagnose")
async def diagnose_inventory(item: InventoryItem):

    product_dict = item.model_dump()

    try:
        from app.llm import get_ai_strategy
    except ImportError:
        from app.llm import get_ai_startegy as get_ai_strategy

    ai_result = get_ai_strategy(product_dict)

    return {
        "status": "success",
        "product_name": item.product_name,
        "stock_status": ai_result.get("status"),
        "judgment": ai_result.get("comment")
    }