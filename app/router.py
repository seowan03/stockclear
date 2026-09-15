from fastapi import APIRouter
from pydantic import BaseModel
from app.llm import get_ai_strategy_safely

router = APIRouter()


# AI 분석에 전달할 데이터 형식
class InventoryItem(BaseModel):
    product_name: str
    stock_qty: int
    purchase_price: int
    received_date: str
    selling_price: int
    sales_qty: int

    storage_days: int
    inventory_value: int
    sales_speed: float
    days_to_sell: float
    depreciation_rate: float


# --- AI 처방전 진단 API ---
@router.post("/api/ai-diagnose")
async def diagnose_inventory(item: InventoryItem):

    product_dict = item.model_dump()

    ai_result = get_ai_strategy_safely(product_dict)

    return {
        "status": "success",
        "product_name": item.product_name,
        "stock_status": ai_result.get("stock_status"),
        "judgment": ai_result.get("judgment")
    }