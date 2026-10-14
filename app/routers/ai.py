import hashlib
import json
import logging
import time
from collections import defaultdict, deque
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.analysis import calculate_risk_score_components, risk_grade_from_score
from app.database import get_db
from app.llm import (
    AIStrategy,
    LLMFailure,
    STRATEGY_METRIC_REFS,
    _validate_strategy_evidence,
    get_ai_strategy,
    render_strategy_text,
    run_llm_with_timeout,
)
from app.models import RawInventory, User
from app.schemas import InventoryItem
from app.security import get_current_user
from app.services.inventory_service import query_user_analysis

router = APIRouter(tags=["ai"])
logger = logging.getLogger(__name__)
AI_RATE_LIMIT_WINDOW_SECONDS = 60 * 60
AI_RATE_LIMIT_MAX_CALLS = 20
AI_RATE_LIMIT_SWEEP_THRESHOLD = 1_000
AI_INPUT_MAX_CHARS = 3_000
AI_REQUEST_TIMEOUT_SECONDS = 12
DIAGNOSIS_CACHE_VERSION = "v8"
_ai_request_history: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce_ai_rate_limit(user_id: int, client_ip: str) -> None:
    now = time.monotonic()
    cutoff = now - AI_RATE_LIMIT_WINDOW_SECONDS
    if len(_ai_request_history) > AI_RATE_LIMIT_SWEEP_THRESHOLD:
        for key in [key for key, history in _ai_request_history.items() if not history or history[-1] < cutoff]:
            del _ai_request_history[key]
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
    days_to_sell = float(data.get("days_to_sell") or 0)
    status = data.get("risk_grade")
    if status not in {"정상", "주의", "장기", "악성"}:
        components = calculate_risk_score_components(
            storage_days,
            days_to_sell,
            data.get("depreciation_rate") or 0,
        )
        risk_score = sum(float(component) for component in components.values())
        status = risk_grade_from_score(risk_score)

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
    discount_label = "규칙 기반 참고 할인율" if recommendation_source == "rule_based_reference" else "참고 할인율"
    lines = [f"{discount_label} {discount:g}%."]
    if recommended_price is None:
        lines.append("참고 판매가를 계산할 수 없습니다.")
    else:
        price_label = "규칙 기반 참고 판매가" if recommendation_source == "rule_based_reference" else "참고 판매가"
        lines.append(f"{price_label} {recommended_price:,.0f}원.")
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
        notice = (
            f"원가 이하로 내려가지 않도록 할인율을 {applied_discount:g}%로 제한했습니다. "
            "실제 시세 자료가 없어 원가 이하 처분 여부는 담당자가 판단해 주세요."
        )
    else:
        applied_discount = requested_discount
        recommended_price = proposed_price
        notice = ""

    guarded_result["recommended_discount"] = float(applied_discount)
    guarded_result["recommended_price"] = float(recommended_price)
    guarded_result["price_limit_notice"] = notice or None
    return guarded_result


async def _diagnose(
    product_data: dict[str, Any],
    context: dict[str, Any],
    recommendation: dict[str, Any],
    user_id: int,
    request: Request,
) -> dict[str, Any]:
    if len(json.dumps(product_data, ensure_ascii=False, default=str)) > AI_INPUT_MAX_CHARS:
        raise HTTPException(status_code=413, detail="AI 진단 요청 데이터가 너무 큽니다.")
    _enforce_ai_rate_limit(user_id, _client_ip(request))
    try:
        ai_result = await run_llm_with_timeout(
            user_id,
            AI_REQUEST_TIMEOUT_SECONDS,
            get_ai_strategy,
            context,
        )
    except LLMFailure as exc:
        logger.warning(
            "AI diagnosis unavailable (failure_code=%s)",
            exc.failure_code,
            extra={"user_id": user_id, "failure_code": exc.failure_code},
        )
        ai_result = {"status": "분석 오류", "failure_code": exc.failure_code}

    if ai_result.get("status") == "분석 오류":
        diagnosis_detail = _make_fallback_diagnosis(context, recommendation["status"])
        ai_strategy = None
    else:
        diagnosis_detail = _make_diagnosis_detail(ai_result, context, recommendation["status"])
        ai_strategy = ai_result

    result = {
        **recommendation,
        "diagnosis_detail": diagnosis_detail,
        "ai_strategy": ai_strategy,
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
            "market_price_source": market_source,
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


def _diagnosis_cache_hash(context: dict[str, Any], recommendation: dict[str, Any]) -> str:
    cache_input = {
        "version": DIAGNOSIS_CACHE_VERSION,
        "context": context,
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


def _placeholder_meaning(metric: str) -> str:
    return f"{metric}의 서버 저장 분석값입니다."


def _make_diagnosis_detail(
    ai_result: dict[str, Any],
    context: dict[str, Any],
    risk_grade: str,
) -> dict[str, Any]:
    analysis = context["analysis"]
    components = analysis["risk_score_components"]
    item_name = context["item"]["product_name"] or "해당 품목"
    score = analysis["risk_score"]
    headline = f"{item_name} · {risk_grade}"
    if score is not None:
        headline += f" · 위험점수 {score:g}점"

    explanations = {
        entry["metric"]: entry["meaning"]
        for entry in ai_result.get("evidence", [])
        if isinstance(entry, dict)
        and entry.get("metric") in STRATEGY_METRIC_REFS
        and entry.get("meaning")
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
        meaning = explanations.get(metric)
        meaning = render_strategy_text(meaning, context) if meaning else _placeholder_meaning(metric)
        evidence.append({
            "metric": metric,
            "evidence_ref": STRATEGY_METRIC_REFS[metric],
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
        "checks": [check for check in ai_result.get("checks", []) if isinstance(check, str) and check],
    }


def _make_fallback_diagnosis(context: dict[str, Any], risk_grade: str) -> dict[str, Any]:
    detail = _make_diagnosis_detail({"evidence": []}, context, risk_grade)
    detail["source"] = "rule_based_fallback"
    return detail


def _format_diagnosis_comment(result: dict[str, Any]) -> str:
    detail = result["diagnosis_detail"]
    is_ai_explanation = detail["source"] == "ai_explanation"
    lines = [detail["headline"]]
    if not is_ai_explanation:
        lines.append("AI 설명을 만들지 못해 서버 분석 기준으로 안내합니다.")

    evidence = detail["evidence"]
    primary = [item for item in evidence if (item.get("score_contribution") or 0) > 0]
    lines.append("위험점수 반영 항목")
    if primary:
        lines.append(" · ".join(
            f"{item['metric']} {float(item['value']):g}{item['unit']}"
            for item in primary
        ))
    else:
        lines.append("현재 분석에서 위험점수에 반영된 주요 항목은 없습니다.")

    explanations = list(dict.fromkeys(
        item["meaning"].strip()
        for item in primary
        if item.get("meaning", "").strip()
        and item["meaning"].strip() != _placeholder_meaning(item.get("metric", ""))
    ))
    if is_ai_explanation and explanations:
        lines.append("AI 해석")
        lines.append(" ".join(explanations))
    if is_ai_explanation and detail.get("checks"):
        lines.append("AI 확인 항목")
        lines.extend(f"- {_ensure_sentence_ending(check)}" for check in detail["checks"])

    lines.append("가격 참고값")
    if result.get("recommended_price") is not None:
        lines.append(
            f"할인율 {result['recommended_discount']:g}% · "
            f"판매가 {result['recommended_price']:,.0f}원"
        )
        if result.get("price_limit_notice"):
            lines.append(result["price_limit_notice"])
    else:
        lines.append(f"규칙 기준 할인율 {result['recommended_discount']:g}%")
    return "\n".join(lines)


def _validate_cached_diagnosis(
    cached_result: Any,
    context: dict[str, Any],
    expected_pricing: dict[str, Any],
) -> dict[str, Any] | None:
    required_fields = {
        "status",
        "recommended_discount",
        "recommended_price",
        "comment",
        "diagnosis_detail",
        "recommendation_source",
        "price_limit_notice",
        "ai_strategy",
    }
    if not isinstance(cached_result, dict) or set(cached_result) != required_fields:
        return None
    if not isinstance(cached_result.get("comment"), str):
        return None

    for field in (
        "status",
        "recommended_discount",
        "recommended_price",
        "recommendation_source",
        "price_limit_notice",
    ):
        if cached_result[field] != expected_pricing.get(field):
            return None

    ai_strategy = cached_result.get("ai_strategy")
    try:
        validated_ai_result = AIStrategy.model_validate(ai_strategy)
        _validate_strategy_evidence(validated_ai_result, context)
    except Exception:
        return None
    # Cached text is shown as-is, so any dropped entry invalidates the cache.
    if validated_ai_result.model_dump() != ai_strategy:
        return None
    expected_detail = _make_diagnosis_detail(ai_strategy, context, expected_pricing["status"])
    if cached_result.get("diagnosis_detail") != expected_detail:
        return None

    validated_result = dict(cached_result)
    validated_result["comment"] = _format_diagnosis_comment(validated_result)
    return validated_result


@router.post("/api/ai-diagnose")
async def diagnose_inventory(item: InventoryItem, request: Request, current_user: User = Depends(get_current_user)):
    product_data = item.model_dump()
    result = await _diagnose(
        product_data,
        _make_strategy_context(product_data),
        _rule_based_strategy(product_data),
        current_user.user_id,
        request,
    )
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
        "selling_price": int(item.market_price or 0),
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
    context = _make_strategy_context(product_data)
    recommendation = _rule_based_strategy(product_data)
    cache_hash = _diagnosis_cache_hash(context, recommendation)
    expected_pricing = _apply_price_floors(recommendation, product_data)
    result = None
    if (
        analysis.diagnosis_input_hash == cache_hash
        and analysis.diagnosis_cache
        and analysis.ai_diagnosis
        and analysis.action_plans
    ):
        try:
            cached_result = json.loads(analysis.diagnosis_cache)
            result = _validate_cached_diagnosis(
                cached_result,
                context,
                expected_pricing,
            )
            if result is None:
                logger.warning(
                    "Saved AI diagnosis cache rejected",
                    extra={"item_id": item_id, "failure_code": "cache_validation_error"},
                )
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning(
                "Saved AI diagnosis cache rejected",
                extra={
                    "item_id": item_id,
                    "failure_code": "cache_parse_error",
                    "error_type": type(exc).__name__,
                },
            )

    cache_hit = result is not None
    if result is None:
        result = await _diagnose(product_data, context, recommendation, current_user.user_id, request)

    discount = float(result.get("recommended_discount") or 0)
    recommended_price = result.get("recommended_price")
    judgment = result.get("comment") or "진단 결과를 받지 못했습니다."
    price_limit_notice = result.get("price_limit_notice")
    action_plan = _format_action_plan(
        discount,
        recommended_price,
        judgment,
        price_limit_notice,
        result.get("recommendation_source"),
    )
    if (
        not cache_hit
        or analysis.ai_diagnosis != judgment
        or analysis.action_plans != action_plan
    ):
        analysis.ai_diagnosis = judgment
        analysis.recommended_price = recommended_price
        analysis.action_plans = action_plan
        if not cache_hit and result.get("diagnosis_detail", {}).get("source") == "ai_explanation":
            analysis.diagnosis_input_hash = cache_hash
            analysis.diagnosis_cache = json.dumps(result, ensure_ascii=False, sort_keys=True)
        elif not cache_hit:
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
