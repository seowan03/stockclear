from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from app.models import UploadHistory
from app.schemas import InventoryItem

router = APIRouter()


def raise_if_duplicate_upload(db: Session, user_id: int, content_hash: str):
    duplicate = (
        db.query(UploadHistory)
        .filter(
            UploadHistory.user_id == user_id,
            UploadHistory.content_hash == content_hash,
            UploadHistory.status == "성공",
        )
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail=f"이미 같은 내용의 엑셀 데이터가 업로드되어 있습니다."
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