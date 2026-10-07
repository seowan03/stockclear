import asyncio
import hashlib
import json
import logging
import time
from collections import defaultdict, deque
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.analysis import calculate_risk_score_components
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
DIAGNOSIS_CACHE_VERSION = "v3"
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
    status = data.get("risk_grade")
    if status not in {"정상", "주의", "장기", "악성"}:
        if storage_days >= 90 or days_to_sell >= 90 or (stock_qty > 0 and sales_speed <= 0):
            status = "악성"
        elif storage_days >= 60 or days_to_sell >= 60:
            status = "장기"
        elif storage_days >= 45 or days_to_sell >= 45:
            status = "주의"
        else:
            status = "정상"

    discount_by_grade = {"정상": 0, "주의": 10, "장기": 10, "악성": 30}
    return {
        "status": status,
        "recommended_discount": discount_by_grade[status],
        "recommendation_source": "rule_based_reference",
    }


def _ensure_sentence_ending(value: str) -> str:
    sentence = value.strip()
    if sentence and sentence[-1] not in ".!?。！？":
        return f"{sentence}."
    return sentence


def _format_action_plan(
    discount: float,
    recommended_price: float | None,
    judgment: str,
    price_limit_notice: str | None,
    recommendation_source: str | None = None,
) -> str:
    discount_label = "규칙 기반 참고 할인율" if recommendation_source == "rule_based_reference" else "할인율"
    lines = [f"{discount_label} {discount:g}%."]
    if recommended_price is None:
        lines.append("권장 판매가를 계산할 수 없습니다.")
    else:
        lines.append(f"권장 판매가 {recommended_price:,.0f}원.")
    if judgment:
        lines.append(f"AI 진단: {_ensure_sentence_ending(judgment)}")
    if price_limit_notice:
        lines.append(f"조정 사유: {_ensure_sentence_ending(price_limit_notice)}")
    return "\n".join(lines)


def _apply_price_floors(result: dict[str, Any], product_data: dict[str, Any]) -> dict[str, Any]:
    try:
        selling_price = Decimal(str(product_data["selling_price"]))
        purchase_price = Decimal(str(product_data["purchase_price"]))
        recommended_discount = Decimal(str(result.get("recommended_discount", 0)))
    except (KeyError, InvalidOperation, TypeError, ValueError):
        selling_price = Decimal("0")
        purchase_price = Decimal("0")
        recommended_discount = Decimal("0")

    guarded_result = dict(result)
    prices_are_valid = all(
        price.is_finite() and price >= 0
        for price in (selling_price, purchase_price)
    ) and selling_price > 0
    if not prices_are_valid:
        guarded_result["recommended_discount"] = 0
        guarded_result["recommended_price"] = None
        guarded_result["price_limit_notice"] = "기준 가격을 확인할 수 없어 할인을 적용하지 않습니다."
        return guarded_result

    if not recommended_discount.is_finite():
        recommended_discount = Decimal("0")
    requested_discount = min(max(recommended_discount, Decimal("0")), Decimal("100"))
    proposed_price = selling_price * (Decimal("1") - requested_discount / Decimal("100"))

    if proposed_price < purchase_price:
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
            purchase_price,
        )
        notice = f"원가 이하로 내려가지 않도록 할인율을 {applied_discount:g}%로 제한했습니다."
    else:
        applied_discount = requested_discount
        recommended_price = proposed_price
        notice = ""

    guarded_result["recommended_discount"] = float(applied_discount)
    guarded_result["recommended_price"] = float(recommended_price)
    guarded_result["price_limit_notice"] = notice or None
    return guarded_result


async def _diagnose(product_data: dict[str, Any], user_id: int, request: Request) -> dict[str, Any]:
    if len(json.dumps(product_data, ensure_ascii=False, default=str)) > AI_INPUT_MAX_CHARS:
        raise HTTPException(status_code=413, detail="AI 진단 요청 데이터가 너무 큽니다.")
    _enforce_ai_rate_limit(user_id, _client_ip(request))
    recommendation = _rule_based_strategy(product_data)
    context = _make_strategy_context(product_data)
    try:
        ai_result = await asyncio.wait_for(
            asyncio.to_thread(get_ai_strategy, context),
            timeout=AI_REQUEST_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("AI diagnosis request timed out", extra={"user_id": user_id})
        ai_result = {"status": "분석 오류"}

    if ai_result.get("status") == "분석 오류":
        diagnosis_detail = _make_fallback_diagnosis(context, recommendation["status"])
    else:
        diagnosis_detail = _make_diagnosis_detail(ai_result, context, recommendation["status"])

    result = {
        **recommendation,
        "diagnosis_detail": diagnosis_detail,
    }
    result = _apply_price_floors(result, product_data)
    result["comment"] = _format_diagnosis_comment(result)
    return result


def _make_strategy_context(data: dict[str, Any]) -> dict[str, Any]:
    storage_days = data.get("storage_days")
    days_to_sell = data.get("days_to_sell")
    depreciation_rate = data.get("depreciation_rate")
    components = data.get("risk_score_components")
    if components is None and None not in (storage_days, days_to_sell, depreciation_rate):
        components = calculate_risk_score_components(
            storage_days,
            days_to_sell,
            depreciation_rate,
        )

    def component(name: str) -> float | None:
        value = (components or {}).get(name)
        return float(value) if value is not None else None

    market_source = data.get("market_price_source")
    if market_source is None:
        market_source = "mock" if data.get("mock_market_price") is not None else "not_available"

    risk_score = data.get("risk_score")
    if risk_score is None:
        risk_score = data.get("final_score")

    return {
        "item": {
            "item_id": data.get("item_id"),
            "product_name": data.get("product_name"),
            "scope": data.get("scope", "uploaded_inventory"),
            "data_as_of": data.get("analysis_as_of"),
            "stock_qty_uploaded": data.get("stock_qty"),
            "inventory_value_cost_basis": data.get("inventory_value"),
        },
        "pricing": {
            "purchase_price": data.get("purchase_price"),
            "uploaded_selling_price": data.get("selling_price"),
            "market_price": None,
            "market_price_source": market_source,
            "market_price_as_of": None,
        },
        "analysis": {
            "risk_grade": data.get("risk_grade"),
            "risk_score": float(risk_score) if risk_score is not None else None,
            "risk_score_components": {
                "storage_days": storage_days,
                "storage_score": component("storage_score"),
                "days_to_sell": days_to_sell,
                "turnover_score": component("turnover_score"),
                "depreciation_rate": depreciation_rate,
                "depreciation_score": component("depreciation_score"),
            },
            "sales_qty_uploaded": data.get("sales_qty"),
            "sales_velocity_uploaded_basis": data.get("sales_speed"),
        },
        "data_quality": {
            "sales_source": "uploaded_aggregate",
            "daily_sales_is_demo": True,
            "actual_order_history_available": False,
            "actual_market_price_available": False,
            "actual_cost_breakdown_available": False,
            "actual_lead_time_available": False,
        },
    }


def _diagnosis_cache_hash(data: dict[str, Any]) -> str:
    recommendation = _rule_based_strategy(data)
    cache_input = {
        "version": DIAGNOSIS_CACHE_VERSION,
        "context": _make_strategy_context(data),
        "recommendation": {
            "status": recommendation["status"],
            "recommended_discount": recommendation["recommended_discount"],
            "recommendation_source": recommendation["recommendation_source"],
        },
    }
    serialized = json.dumps(
        cache_input,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _make_diagnosis_detail(
    ai_result: dict[str, Any],
    context: dict[str, Any],
    risk_grade: str,
) -> dict[str, Any]:
    analysis = context["analysis"]
    components = analysis["risk_score_components"]
    item_name = context["item"]["product_name"] or "해당 품목"
    score = analysis["risk_score"]
    headline = f"{item_name}은 서버 분석 기준 {risk_grade} 등급"
    if score is not None:
        headline += f", 위험점수 {score:g}점"
    headline += "입니다."

    explanations = {
        entry["metric"]: entry["meaning"]
        for entry in ai_result.get("evidence", [])
        if isinstance(entry, dict)
    }
    evidence_specs = [
        ("보관 기간", components["storage_days"], "일", components["storage_score"], 40),
        (
            "업로드 판매 속도",
            analysis["sales_velocity_uploaded_basis"],
            "개/일",
            None,
            None,
        ),
        (
            "예상 소진 기간",
            components["days_to_sell"],
            "일",
            components["turnover_score"],
            30,
        ),
        (
            "원가 대비 판매가 차이",
            components["depreciation_rate"],
            "%",
            components["depreciation_score"],
            30,
        ),
    ]
    evidence = []
    for metric, value, unit, contribution, maximum in evidence_specs:
        if value is None:
            continue
        meaning = explanations.get(metric) or f"{metric}의 서버 저장 분석값입니다."
        evidence.append({
            "metric": metric,
            "value": value,
            "unit": unit,
            "score_contribution": contribution,
            "score_maximum": maximum,
            "meaning": meaning,
        })

    return {
        "source": "ai_explanation",
        "headline": headline,
        "evidence": evidence,
    }


def _make_fallback_diagnosis(context: dict[str, Any], risk_grade: str) -> dict[str, Any]:
    fallback = {
        "evidence": [
            {
                "metric": "보관 기간",
                "meaning": "보관 기간이 길어 재고 체류 상태를 확인할 필요가 있습니다.",
            },
            {
                "metric": "예상 소진 기간",
                "meaning": "예상 소진 기간은 업로드 판매 속도를 기준으로 계산한 값입니다.",
            },
            {
                "metric": "원가 대비 판매가 차이",
                "meaning": "원가와 업로드 판매가를 비교한 값입니다.",
            },
        ],
    }
    detail = _make_diagnosis_detail(fallback, context, risk_grade)
    detail["source"] = "rule_based_fallback"
    return detail


def _format_diagnosis_comment(result: dict[str, Any]) -> str:
    detail = result["diagnosis_detail"]
    grade = result.get("status")
    source_label = "AI 설명" if detail["source"] == "ai_explanation" else "규칙 기반 진단"
    focus_label = "우선 확인 대상" if grade in {"장기", "악성"} else "현재 분석 요약"
    lines = [f"{source_label} · {focus_label}", detail["headline"]]

    evidence = detail["evidence"]
    primary = [item for item in evidence if (item.get("score_contribution") or 0) > 0]
    if primary:
        main_causes = "과 ".join(
            f"{item['metric']} {float(item['value']):g}{item['unit']}"
            f"({float(item['score_contribution']):g}/{float(item['score_maximum']):g}점)"
            for item in primary
        )
        lines.append(f"주요 원인은 {main_causes}입니다.")
        if detail["source"] == "ai_explanation":
            explanations = list(dict.fromkeys(
                item["meaning"].strip()
                for item in primary
                if item.get("meaning", "").strip()
            ))
            if explanations:
                lines.append(f"AI 해석: {' '.join(explanations)}")
    else:
        lines.append("현재 저장된 분석에서 점수를 높인 주요 항목은 없습니다.")

    non_contributing = [
        item for item in evidence
        if item.get("score_contribution") == 0 and item.get("score_maximum") is not None
    ]
    for item in non_contributing:
        lines.append(
            f"{item['metric']}는 {float(item['value']):g}{item['unit']}로 저장되어 있으며 "
            f"위험점수 기여는 0/{float(item['score_maximum']):g}점입니다."
        )

    sales_velocity = next(
        (item for item in evidence if item["metric"] == "업로드 판매 속도"),
        None,
    )
    if sales_velocity is not None:
        lines.append(
            f"업로드 기준 판매 속도는 {float(sales_velocity['value']):g}개/일입니다. "
            "이는 업로드 누계 판매량과 보관 기간으로 계산한 값이지, 최근 판매 추세 분석은 아닙니다."
        )

    lines.append("가격 참고값")
    lines.append(
        f"현재 시스템의 규칙 기반 참고 할인율은 {result['recommended_discount']:g}%, "
        "추천 판매가는 "
        f"{result['recommended_price']:,.0f}원입니다."
        if result.get("recommended_price") is not None
        else f"현재 시스템의 규칙 기반 참고 할인율은 {result['recommended_discount']:g}%입니다."
    )
    if result.get("recommended_price") is not None:
        if result.get("price_limit_notice"):
            lines.append(f"가격 제한: {result['price_limit_notice']}")
    return "\n".join(lines)


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
        "diagnosis_detail": result.get("diagnosis_detail"),
        "recommendation_source": result.get("recommendation_source"),
        "price_limit_notice": result.get("price_limit_notice"),
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
    score_inputs = (analysis.aging_days, analysis.days_to_sell, analysis.fluctuation_rate)
    risk_score_components = None
    if all(value is not None for value in score_inputs):
        risk_score_components = calculate_risk_score_components(*score_inputs)
    product_data = {
        "item_id": item.item_id,
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
        "risk_grade": analysis.risk_grade,
        "risk_score": float(analysis.final_score) if analysis.final_score is not None else None,
        "risk_score_components": risk_score_components,
        "analysis_as_of": analysis.updated_at.isoformat() if analysis.updated_at else None,
        "market_price_source": "mock" if item.mock_market_price is not None else "not_available",
    }
    cache_hash = _diagnosis_cache_hash(product_data)
    result = None
    if (
        analysis.diagnosis_input_hash == cache_hash
        and analysis.diagnosis_cache
        and analysis.ai_diagnosis
        and analysis.action_plans
    ):
        try:
            cached_result = json.loads(analysis.diagnosis_cache)
            required_fields = {
                "status",
                "recommended_discount",
                "recommended_price",
                "comment",
                "diagnosis_detail",
                "recommendation_source",
                "price_limit_notice",
            }
            if isinstance(cached_result, dict) and required_fields.issubset(cached_result):
                result = cached_result
        except (json.JSONDecodeError, TypeError):
            logger.warning("Saved AI diagnosis cache is invalid", extra={"item_id": item_id})

    cache_hit = result is not None
    if result is None:
        result = await _diagnose(product_data, current_user.user_id, request)

    discount = float(result.get("recommended_discount") or 0)
    recommended_price = result.get("recommended_price")
    judgment = result.get("comment") or "진단 결과를 받지 못했습니다."
    price_limit_notice = result.get("price_limit_notice")
    if not cache_hit:
        analysis.ai_diagnosis = judgment
        analysis.recommended_price = recommended_price
        analysis.action_plans = _format_action_plan(
            discount,
            recommended_price,
            judgment,
            price_limit_notice,
            result.get("recommendation_source"),
        )
        if result.get("diagnosis_detail", {}).get("source") == "ai_explanation":
            analysis.diagnosis_input_hash = cache_hash
            analysis.diagnosis_cache = json.dumps(result, ensure_ascii=False, sort_keys=True)
        else:
            analysis.diagnosis_input_hash = None
            analysis.diagnosis_cache = None
        db.commit()

    return {
        "status": "success",
        "item_id": item_id,
        "stock_status": result.get("status"),
        "recommended_discount": discount,
        "recommended_price": recommended_price,
        "judgment": judgment,
        "diagnosis_detail": result.get("diagnosis_detail"),
        "recommendation_source": result.get("recommendation_source"),
        "price_limit_notice": price_limit_notice,
        "action_plans": analysis.action_plans,
        "cache_hit": cache_hit,
    }
