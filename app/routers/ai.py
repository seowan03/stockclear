import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from decimal import Decimal, InvalidOperation, ROUND_DOWN
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


def _apply_price_floors(result: dict[str, Any], product_data: dict[str, Any]) -> dict[str, Any]:
    try:
        selling_price = Decimal(str(product_data["selling_price"]))
        purchase_price = Decimal(str(product_data["purchase_price"]))
        market_price_value = product_data.get("current_market_price")
        if market_price_value is None:
            market_price_value = product_data.get("mock_market_price")
        if market_price_value is None:
            market_price_value = selling_price
        market_price = Decimal(str(market_price_value))
        recommended_discount = Decimal(str(result.get("recommended_discount", 0)))
    except (KeyError, InvalidOperation, TypeError, ValueError):
        selling_price = Decimal("0")
        purchase_price = Decimal("0")
        market_price = Decimal("0")
        recommended_discount = Decimal("0")

    guarded_result = dict(result)
    comment = str(guarded_result.get("comment") or "").strip()
    prices_are_valid = all(
        price.is_finite() and price >= 0
        for price in (selling_price, purchase_price, market_price)
    ) and selling_price > 0 and market_price > 0
    if not prices_are_valid:
        guarded_result["recommended_discount"] = 0
        guarded_result["recommended_price"] = None
        guarded_result["comment"] = f"{comment} 기준 가격을 확인할 수 없어 할인을 적용하지 않습니다.".strip()
        return guarded_result

    if not recommended_discount.is_finite():
        recommended_discount = Decimal("0")
    requested_discount = min(max(recommended_discount, Decimal("0")), Decimal("100"))
    proposed_price = selling_price * (Decimal("1") - requested_discount / Decimal("100"))
    price_floor = max(market_price, purchase_price)

    if proposed_price < market_price:
        applied_discount = Decimal("0")
        recommended_price = price_floor
        notice = f"할인 적용가가 시세보다 낮아 할인율을 0%로 조정하고 {recommended_price:g}원 판매를 권장합니다."
    elif proposed_price < purchase_price:
        if selling_price <= purchase_price:
            maximum_discount = Decimal("0")
        else:
            maximum_discount = ((selling_price - purchase_price) / selling_price * 100).quantize(
                Decimal("0.01"),
                rounding=ROUND_DOWN,
            )
        applied_discount = min(requested_discount, maximum_discount)
        recommended_price = max(
            selling_price * (Decimal("1") - applied_discount / Decimal("100")),
            price_floor,
        )
        notice = f"원가 이하로 내려가지 않도록 할인율을 {applied_discount:g}%로 제한했습니다."
    else:
        applied_discount = requested_discount
        recommended_price = max(proposed_price, price_floor)
        notice = ""

    guarded_result["recommended_discount"] = float(applied_discount)
    guarded_result["recommended_price"] = float(recommended_price)
    if notice:
        guarded_result["comment"] = f"{comment} {notice}".strip()
    return guarded_result


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
    return _apply_price_floors(result, product_data)


@router.post("/api/ai-diagnose")
async def diagnose_inventory(item: InventoryItem, request: Request, current_user: User = Depends(get_current_user)):
    result = await _diagnose(item.model_dump(), current_user.user_id, request)
    return {
        "status": "success",
        "product_name": item.product_name,
        "stock_status": result.get("status"),
        "recommended_discount": result.get("recommended_discount", 0),
        "recommended_price": result.get("recommended_price"),
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
        "mock_market_price": float(item.mock_market_price) if item.mock_market_price is not None else None,
        "current_market_price": float(item.mock_market_price or item.market_price or 0),
        "sales_qty": item.sales_qty or 0,
        "storage_days": analysis.aging_days or 0,
        "inventory_value": int(analysis.inventory_amount or 0),
        "sales_speed": float(analysis.sales_velocity or 0),
        "days_to_sell": analysis.days_to_sell or 0,
        "depreciation_rate": float(analysis.fluctuation_rate or 0),
    }
    result = await _diagnose(product_data, current_user.user_id, request)
    discount = float(result.get("recommended_discount") or 0)
    recommended_price = result.get("recommended_price")
    judgment = result.get("comment") or "진단 결과를 받지 못했습니다."
    analysis.ai_diagnosis = judgment
    analysis.recommended_price = recommended_price
    sale_price_text = f"{recommended_price:,.0f}원 판매 권장" if recommended_price is not None else "권장 판매가 확인 필요"
    analysis.action_plans = f"{discount:g}% 할인 권장, {sale_price_text}: {judgment}" if discount else f"할인율 0%, {sale_price_text}: {judgment}"
    db.commit()
    return {
        "status": "success",
        "item_id": item_id,
        "stock_status": result.get("status"),
        "recommended_discount": discount,
        "recommended_price": recommended_price,
        "judgment": judgment,
        "action_plans": analysis.action_plans,
    }
