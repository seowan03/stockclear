import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.llm import get_ai_strategy
from app.models import User
from app.schemas import InventoryItem
from app.security import get_current_user

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


@router.post("/api/ai-diagnose")
async def diagnose_inventory(item: InventoryItem, request: Request, current_user: User = Depends(get_current_user)):
    product_data = item.model_dump()
    if len(json.dumps(product_data, ensure_ascii=False, default=str)) > AI_INPUT_MAX_CHARS:
        raise HTTPException(status_code=413, detail="AI 진단 요청 데이터가 너무 큽니다.")
    _enforce_ai_rate_limit(current_user.user_id, _client_ip(request))
    try:
        result = await asyncio.wait_for(asyncio.to_thread(get_ai_strategy, product_data), timeout=AI_REQUEST_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logger.warning("AI diagnosis request timed out", extra={"user_id": current_user.user_id})
        result = _rule_based_strategy(product_data)
    if result.get("status") == "분석 오류":
        result = _rule_based_strategy(product_data)
    return {"status": "success", "product_name": item.product_name, "stock_status": result.get("status"), "judgment": result.get("comment")}
