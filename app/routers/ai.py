import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.llm import get_ai_strategy
from app.models import AnalysisResult, RawInventory, User
from app.schemas import InventoryItem
from app.security import get_current_user
from app.services.inventory_service import query_user_analysis

router = APIRouter(tags=["ai"])
logger = logging.getLogger(__name__)
AI_RATE_LIMIT_WINDOW_SECONDS = 60 * 60
AI_RATE_LIMIT_MAX_CALLS = 20
AI_INPUT_MAX_CHARS = 3_000
AI_REQUEST_TIMEOUT_SECONDS = 12
_ai_request_history: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce_ai_rate_limit(user_id: int, client_ip: str) -> None:
    now = time.monotonic()
    cutoff = now - AI_RATE_LIMIT_WINDOW_SECONDS
    keys = (f"user:{user_id}", f"ip:{client_ip}")
    for key in keys:
        history = _ai_request_history[key]
        while history and history[0] < cutoff:
            history.popleft()
        if len(history) >= AI_RATE_LIMIT_MAX_CALLS:
            raise HTTPException(status_code=429, detail="AI 진단 요청이 너무 많습니다. 잠시 후 다시 시도해주세요.")
    for key in keys:
        _ai_request_history[key].append(now)


def _rule_based_strategy(data: dict[str, Any]) -> dict[str, Any]:
    storage_days = int(data.get("storage_days") or 0)
    stock_qty = int(data.get("stock_qty") or 0)
    sales_speed = float(data.get("sales_speed") or 0)
    days_to_sell = float(data.get("days_to_sell") or 0)
    if storage_days >= 90 or days_to_sell >= 90 or (stock_qty > 0 and sales_speed <= 0):
        return {"status": "악성재고 위험", "recommended_discount": 30, "comment": "AI 진단을 사용할 수 없어 규칙 기반으로 판단했습니다."}
    if storage_days >= 45 or days_to_sell >= 45:
        return {"status": "주의", "recommended_discount": 10, "comment": "AI 진단을 사용할 수 없어 규칙 기반으로 판단했습니다."}
    return {"status": "양호", "recommended_discount": 0, "comment": "AI 진단을 사용할 수 없어 규칙 기반으로 판단했습니다."}


async def _diagnose(product_data: dict[str, Any], user_id: int, request: Request) -> dict[str, Any]:
    if len(json.dumps(product_data, ensure_ascii=False, default=str)) > AI_INPUT_MAX_CHARS:
        raise HTTPException(status_code=413, detail="AI 진단 요청 데이터가 너무 큽니다.")
    _enforce_ai_rate_limit(user_id, _client_ip(request))
    try:
        result = await asyncio.wait_for(asyncio.to_thread(get_ai_strategy, product_data), timeout=AI_REQUEST_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logger.warning("AI diagnosis request timed out", extra={"user_id": user_id})
        result = _rule_based_strategy(product_data)
    if result.get("status") == "분석 오류":
        result = _rule_based_strategy(product_data)
    return result


@router.post("/api/ai-diagnose")
async def diagnose_inventory(item: InventoryItem, request: Request, current_user: User = Depends(get_current_user)):
    result = await _diagnose(item.model_dump(), current_user.user_id, request)
    return {
        "status": "success",
        "product_name": item.product_name,
        "stock_status": result.get("status"),
        "recommended_discount": result.get("recommended_discount", 0),
        "judgment": result.get("comment"),
    }


@router.post("/api/inventory/{item_id}/ai-diagnose")
async def diagnose_saved_inventory(
    item_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = query_user_analysis(db, current_user.user_id).filter(RawInventory.item_id == item_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="해당 재고를 찾을 수 없습니다.")

    analysis, item = row
    product_data = {
        "product_name": item.product_name,
        "stock_qty": item.stock_qty or 0,
        "purchase_price": int(item.purchase_price or 0),
        "received_date": item.inbound_date.isoformat() if item.inbound_date else "",
        "selling_price": int(item.market_price or 0),
        "sales_qty": item.sales_qty or 0,
        "storage_days": analysis.aging_days or 0,
        "inventory_value": int(analysis.inventory_amount or 0),
        "sales_speed": float(analysis.sales_velocity or 0),
        "days_to_sell": analysis.days_to_sell or 0,
        "depreciation_rate": float(analysis.fluctuation_rate or 0),
    }
    result = await _diagnose(product_data, current_user.user_id, request)
    discount = float(result.get("recommended_discount") or 0)
    judgment = result.get("comment") or "진단 결과를 받지 못했습니다."
    analysis.ai_diagnosis = judgment
    analysis.action_plans = f"{discount:g}% 할인 권장: {judgment}" if discount else f"할인 불필요: {judgment}"
    db.commit()
    return {
        "status": "success",
        "item_id": item_id,
        "stock_status": result.get("status"),
        "recommended_discount": discount,
        "judgment": judgment,
        "action_plans": analysis.action_plans,
    }
