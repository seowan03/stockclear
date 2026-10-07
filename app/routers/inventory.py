import json
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.analysis import calculate_date_based_days_to_sell, calculate_safety_stock
from app.config import RISK_GRADE_META
from app.database import get_db
from app.models import AnalysisResult, InventoryDailyMetric, RawInventory, StrategyAction, UploadAnalysisSummary, UploadHistory, User
from app.schemas import InventoryGridBatchUpdate, InventorySellingBatchUpdate, InventorySellingUpdate, SafetyStockCalculation
from app.security import get_current_user
from app.services.inventory_service import (
    make_user_summary_input,
    mark_latest_upload_summary_stale,
    query_user_analysis,
    update_inventory_grid,
)
from app.services.mock_market_price import generate_mock_market_price

router = APIRouter(tags=["inventory"])


def _recommended_qty_by_item_id(db: Session, item_ids: list[int]) -> dict[int, int]:
    if not item_ids:
        return {}

    ranked_daily_sales = db.query(
        InventoryDailyMetric.item_id.label("item_id"),
        InventoryDailyMetric.daily_sales_qty.label("daily_sales_qty"),
        func.row_number().over(
            partition_by=InventoryDailyMetric.item_id,
            order_by=InventoryDailyMetric.business_date.desc(),
        ).label("row_number"),
    ).filter(
        InventoryDailyMetric.item_id.in_(item_ids),
        InventoryDailyMetric.business_date <= date.today(),
    ).subquery()
    daily_sales_stats = db.query(
        ranked_daily_sales.c.item_id,
        func.max(ranked_daily_sales.c.daily_sales_qty).label("max_daily_sales"),
        func.avg(ranked_daily_sales.c.daily_sales_qty).label("average_daily_sales"),
    ).filter(
        ranked_daily_sales.c.row_number <= 30,
    ).group_by(
        ranked_daily_sales.c.item_id,
    ).all()
    return {
        stats.item_id: calculate_safety_stock(
            max_daily_sales=float(stats.max_daily_sales),
            average_daily_sales=float(stats.average_daily_sales),
            max_lead_time_days=5,
            average_lead_time_days=2,
        )
        for stats in daily_sales_stats
    }


@router.get("/api/dashboard")
def get_dashboard(upload_id: int | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    upload = None
    if upload_id is not None:
        upload = db.query(UploadHistory).filter(
            UploadHistory.id == upload_id,
            UploadHistory.user_id == current_user.user_id,
        ).first()
        if not upload:
            raise HTTPException(status_code=404, detail="업로드 기록을 찾을 수 없습니다.")
    rows = query_user_analysis(
        db,
        current_user.user_id,
        upload_file_id=upload.id if upload else None,
        upload_content_hash=upload.content_hash if upload else None,
    ).all()
    inventory_value = round(sum(float(item.stock_qty or 0) * float(item.purchase_price or 0) for _, item in rows))
    if not rows:
        return {
            "total_sku": 0,
            "risk_count": 0,
            "aging_count": 0,
            "inventory_value": 0,
            "grades": [],
            "risk_items": [],
            "upload_file_name": upload.file_name if upload else None,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    counts = {}
    risk_count = aging_count = 0
    for analysis, _ in rows:
        counts[analysis.risk_grade] = counts.get(analysis.risk_grade, 0) + 1
        if analysis.risk_grade == "악성":
            risk_count += 1
        if analysis.risk_grade == "장기":
            aging_count += 1
    risk_items = sorted(({"product_name": item.product_name, "final_score": analysis.final_score} for analysis, item in rows), key=lambda value: value["final_score"], reverse=True)[:5]
    return {
        "total_sku": len(rows),
        "risk_count": risk_count,
        "aging_count": aging_count,
        "inventory_value": inventory_value,
        "grades": [{"name": name, "count": count, "color": RISK_GRADE_META.get(name, {}).get("color", "#64748b")} for name, count in counts.items()],
        "risk_items": risk_items,
        "upload_file_name": upload.file_name if upload else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/api/inventory")
def list_inventory(search: str = "", status: str = "", upload_id: int | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    upload = None
    if upload_id is not None:
        upload = db.query(UploadHistory).filter(
            UploadHistory.id == upload_id,
            UploadHistory.user_id == current_user.user_id,
        ).first()
        if not upload:
            raise HTTPException(status_code=404, detail="업로드 기록을 찾을 수 없습니다.")
    query = query_user_analysis(
        db,
        current_user.user_id,
        upload_file_id=upload.id if upload else None,
        upload_content_hash=upload.content_hash if upload else None,
    )
    if search:
        query = query.filter(RawInventory.product_name.contains(search))
    if status:
        query = query.filter(AnalysisResult.risk_grade == status)
    rows = query.order_by(AnalysisResult.final_score.desc()).all()
    recommended_qty_by_item_id = _recommended_qty_by_item_id(
        db,
        [item.item_id for _, item in rows],
    )

    return {"upload_file_name": upload.file_name if upload else None, "items": [{
        "item_id": item.item_id,
        "version": item.version,
        "edited_at": item.edited_at.isoformat() if item.edited_at else None,
        "product_name": item.product_name,
        "stock_qty": item.stock_qty,
        "purchase_price": float(item.purchase_price or 0),
        "selling_price": float(item.market_price or 0),
        "mock_market_price": float(item.mock_market_price) if item.mock_market_price is not None else None,
        "recommended_price": float(analysis.recommended_price) if analysis.recommended_price is not None else None,
        "received_date": item.inbound_date.isoformat() if item.inbound_date else None,
        "sales_speed": float(analysis.sales_velocity or 0),
        "sales_qty": item.sales_qty,
        "is_selling": item.is_selling,
        "storage_days": analysis.aging_days,
        "days_to_sell": analysis.days_to_sell,
        "final_score": float(analysis.final_score or 0),
        "depreciation_rate": float(analysis.fluctuation_rate or 0),
        "inventory_value": float(analysis.inventory_amount or 0),
        "risk_grade": analysis.risk_grade,
        "recommended_qty": recommended_qty_by_item_id.get(item.item_id),
        "action_plans": analysis.action_plans,
        "ai_diagnosis": analysis.ai_diagnosis,
    } for analysis, item in rows]}


@router.patch("/api/inventory/batch")
def edit_inventory_grid(payload: InventoryGridBatchUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    try:
        items = update_inventory_grid(db, current_user.user_id, payload)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"items": items}


@router.get("/api/inventory/daily")
def list_daily_inventory(
    business_date: date,
    upload_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    upload = None
    if upload_id is not None:
        upload = db.query(UploadHistory).filter(
            UploadHistory.id == upload_id,
            UploadHistory.user_id == current_user.user_id,
        ).first()
        if not upload:
            raise HTTPException(status_code=404, detail="업로드 기록을 찾을 수 없습니다.")

    query = db.query(InventoryDailyMetric, RawInventory).join(
        RawInventory,
        RawInventory.item_id == InventoryDailyMetric.item_id,
    ).filter(
        RawInventory.user_id == current_user.user_id,
        RawInventory.is_deleted.is_(False),
        InventoryDailyMetric.business_date == business_date,
    )
    if upload is not None:
        upload_filter = RawInventory.upload_file_id == upload.id
        if upload.content_hash:
            upload_filter = or_(
                upload_filter,
                and_(
                    RawInventory.upload_file_id.is_(None),
                    RawInventory.upload_batch_id == upload.content_hash,
                ),
            )
        query = query.filter(upload_filter)

    weekday_names = ("월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일")
    rows = query.order_by(RawInventory.item_id).all()
    weekly_sales_by_item_id = {}
    item_ids = [item.item_id for _, item in rows]
    if item_ids:
        weekly_sales_stats = db.query(
            InventoryDailyMetric.item_id,
            func.sum(InventoryDailyMetric.daily_sales_qty).label("weekly_sales_qty"),
            func.count(InventoryDailyMetric.metric_id).label("recorded_days"),
        ).filter(
            InventoryDailyMetric.item_id.in_(item_ids),
            InventoryDailyMetric.business_date >= business_date - timedelta(days=6),
            InventoryDailyMetric.business_date <= business_date,
        ).group_by(
            InventoryDailyMetric.item_id,
        ).all()
        weekly_sales_by_item_id = {
            stats.item_id: {
                "weekly_sales_qty": int(stats.weekly_sales_qty or 0),
                "weekly_sales_recorded_days": int(stats.recorded_days or 0),
            }
            for stats in weekly_sales_stats
        }
    date_based_days_to_sell_by_item_id = {
        item.item_id: calculate_date_based_days_to_sell(
            remaining_stock_qty=metric.remaining_stock_qty,
            weekly_sales_qty=weekly_sales_by_item_id.get(item.item_id, {}).get("weekly_sales_qty"),
            recorded_days=weekly_sales_by_item_id.get(item.item_id, {}).get("weekly_sales_recorded_days", 0),
        )
        for metric, item in rows
    }
    return {
        "business_date": business_date.isoformat(),
        "weekday": weekday_names[business_date.weekday()],
        "items": [{
            "item_id": item.item_id,
            "product_name": item.product_name,
            "business_date": metric.business_date.isoformat(),
            "weekday": weekday_names[metric.business_date.weekday()],
            "daily_sales_qty": metric.daily_sales_qty,
            "remaining_stock_qty": metric.remaining_stock_qty,
            "weekly_sales_qty": weekly_sales_by_item_id.get(item.item_id, {}).get("weekly_sales_qty"),
            "weekly_sales_recorded_days": weekly_sales_by_item_id.get(item.item_id, {}).get("weekly_sales_recorded_days", 0),
            "days_to_sell_on_date": date_based_days_to_sell_by_item_id[item.item_id],
            "daily_selling_price": float(metric.daily_selling_price),
            "price_variation_rate": float(metric.price_variation_rate),
        } for metric, item in rows],
    }


@router.post("/api/inventory/{item_id}/refresh-market-price")
def refresh_inventory_market_price(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = query_user_analysis(db, current_user.user_id).filter(RawInventory.item_id == item_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="해당 재고를 찾을 수 없습니다.")

    analysis, item = row
    new_market_price = generate_mock_market_price(
        item.market_price,
        previous_price=item.mock_market_price,
    )
    if new_market_price is None:
        raise HTTPException(status_code=409, detail="현재 판매가 범위에서 변경 가능한 시세를 생성할 수 없습니다.")

    item.mock_market_price = new_market_price
    analysis.recommended_price = None
    analysis.diagnosis_input_hash = None
    analysis.diagnosis_cache = None
    stale_message = "더미 시세가 갱신되었습니다. 새 시세 기준으로 AI 진단을 다시 실행해주세요."
    analysis.ai_diagnosis = stale_message
    analysis.action_plans = stale_message
    db.commit()
    return {
        "status": "success",
        "item_id": item_id,
        "mock_market_price": float(item.mock_market_price),
        "recommended_price": None,
        "action_plans": analysis.action_plans,
    }


@router.delete("/api/inventory/{item_id}")
def delete_inventory_item(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.query(RawInventory).filter(
        RawInventory.item_id == item_id,
        RawInventory.user_id == current_user.user_id,
        RawInventory.is_deleted.is_(False),
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="해당 재고를 찾을 수 없습니다.")
    db.query(InventoryDailyMetric).filter(
        InventoryDailyMetric.item_id == item_id,
    ).delete(synchronize_session=False)
    db.query(AnalysisResult).filter(
        AnalysisResult.item_id == item_id,
    ).delete(synchronize_session=False)
    db.delete(item)
    mark_latest_upload_summary_stale(db, current_user.user_id)
    db.commit()
    return {"status": "deleted", "item_id": item_id}


@router.get("/api/inventory/{item_id}")
def get_inventory_item(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = query_user_analysis(db, current_user.user_id).filter(RawInventory.item_id == item_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="해당 재고를 찾을 수 없습니다.")
    analysis, item = row
    return {"item_id": item.item_id, "product_name": item.product_name, "stock_qty": item.stock_qty, "is_selling": item.is_selling, "aging_days": analysis.aging_days, "days_to_sell": analysis.days_to_sell, "risk_grade": analysis.risk_grade, "ai_diagnosis": analysis.ai_diagnosis}


@router.patch("/api/inventory/{item_id}/selling")
def update_inventory_selling(item_id: int, payload: InventorySellingUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.query(RawInventory).filter(
        RawInventory.item_id == item_id,
        RawInventory.user_id == current_user.user_id,
        RawInventory.is_deleted.is_(False),
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="해당 재고를 찾을 수 없습니다.")
    item.is_selling = payload.is_selling
    db.commit()
    return {"item_id": item_id, "is_selling": item.is_selling}


@router.post("/api/inventory/selling")
def update_inventory_selling_batch(payload: InventorySellingBatchUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item_ids = list(dict.fromkeys(payload.item_ids))
    if not item_ids:
        raise HTTPException(status_code=422, detail="판매할 재고를 하나 이상 선택해 주세요.")

    items = db.query(RawInventory).filter(
        RawInventory.item_id.in_(item_ids),
        RawInventory.user_id == current_user.user_id,
        RawInventory.is_deleted.is_(False),
    ).all()
    found_ids = {item.item_id for item in items}
    missing_ids = [item_id for item_id in item_ids if item_id not in found_ids]
    if missing_ids:
        raise HTTPException(status_code=404, detail="선택한 재고 중 일부를 찾을 수 없습니다.")

    for item in items:
        item.is_selling = payload.is_selling
    db.commit()
    return {"items": [{"item_id": item.item_id, "is_selling": item.is_selling} for item in items]}


@router.get("/api/strategy")
def get_strategy(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = db.query(AnalysisResult.risk_grade, func.count(AnalysisResult.result_id)).join(RawInventory, AnalysisResult.item_id == RawInventory.item_id).filter(RawInventory.user_id == current_user.user_id, RawInventory.is_deleted.is_(False)).group_by(AnalysisResult.risk_grade).all()
    active_items = query_user_analysis(db, current_user.user_id)
    order_count = active_items.filter(AnalysisResult.risk_grade == "악성").count()
    promotion_count = active_items.filter(AnalysisResult.risk_grade == "장기").count()
    return {
        "groups": [{"type": grade, "title": RISK_GRADE_META.get(grade, {}).get("title", grade), "summary": RISK_GRADE_META.get(grade, {}).get("summary", ""), "count": count} for grade, count in rows],
        "order_count": order_count,
        "promotion_count": promotion_count,
    }


@router.get("/api/strategy/actions")
def list_strategy_actions(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    actions = db.query(StrategyAction).filter(
        StrategyAction.user_id == current_user.user_id
    ).order_by(StrategyAction.created_at.desc()).all()
    return {"actions": [{
        "action_id": action.action_id,
        "action_type": action.action_type,
        "status": action.status,
        "item_count": len(json.loads(action.item_ids)),
        "created_at": action.created_at.isoformat() if action.created_at else None,
    } for action in actions]}


@router.post("/api/strategy/actions")
def create_strategy_action(action_type: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if action_type not in ("order", "promotion"):
        raise HTTPException(status_code=422, detail="지원하지 않는 전략 작업입니다.")
    query = query_user_analysis(db, current_user.user_id)
    if action_type == "order":
        query = query.filter(AnalysisResult.risk_grade == "악성")
    else:
        query = query.filter(RawInventory.is_deleted.is_(False), AnalysisResult.risk_grade == "장기")
    item_ids = [item.item_id for _, item in query.all()]
    if not item_ids:
        raise HTTPException(status_code=409, detail="처리할 대상 재고가 없습니다.")
    action = StrategyAction(
        user_id=current_user.user_id,
        action_type=action_type,
        item_ids=json.dumps(item_ids),
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return {"action_id": action.action_id, "action_type": action.action_type, "status": action.status, "item_count": len(item_ids)}


@router.get("/api/inventory/{item_id}/safety-stock")
def get_inventory_safety_stock_inputs(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = query_user_analysis(db, current_user.user_id).filter(RawInventory.item_id == item_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="해당 재고를 찾을 수 없습니다.")
    analysis, _ = row
    metrics = db.query(InventoryDailyMetric).filter(
        InventoryDailyMetric.item_id == item_id,
        InventoryDailyMetric.business_date <= date.today(),
    )
    latest_date = metrics.with_entities(func.max(InventoryDailyMetric.business_date)).scalar()
    window_start = latest_date - timedelta(days=29) if latest_date else None
    recorded_days = 0
    maximum_sales = None
    average_sales = float(analysis.sales_velocity or 0)
    if latest_date:
        recorded_days, maximum_sales, average_sales = metrics.filter(
            InventoryDailyMetric.business_date >= window_start,
        ).with_entities(
            func.count(InventoryDailyMetric.metric_id),
            func.max(InventoryDailyMetric.daily_sales_qty),
            func.avg(InventoryDailyMetric.daily_sales_qty),
        ).one()
    return {
        "item_id": item_id,
        "inputs": {
            "max_daily_sales": maximum_sales,
            "average_daily_sales": float(average_sales),
            "max_lead_time_days": 5,
            "average_lead_time_days": 2,
        },
        "recorded_days": recorded_days,
        "window_start": window_start.isoformat() if window_start else None,
        "window_end": latest_date.isoformat() if latest_date else None,
        "source": "stored_daily_demo" if recorded_days else "estimate",
    }


@router.post("/api/inventory/{item_id}/safety-stock")
def calculate_inventory_safety_stock(
    item_id: int,
    payload: SafetyStockCalculation,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = query_user_analysis(db, current_user.user_id).filter(RawInventory.item_id == item_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="해당 재고를 찾을 수 없습니다.")
    return {
        "item_id": item_id,
        "recommended_qty": calculate_safety_stock(**payload.model_dump()),
        "inputs": payload.model_dump(),
        "source": "manual",
    }


@router.get("/api/export")
def get_export(upload_id: int | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    upload = None
    if upload_id is not None:
        upload = db.query(UploadHistory).filter(
            UploadHistory.id == upload_id,
            UploadHistory.user_id == current_user.user_id,
        ).first()
        if not upload:
            raise HTTPException(status_code=404, detail="업로드 기록을 찾을 수 없습니다.")
    summary_upload = upload or db.query(UploadHistory).filter(
        UploadHistory.user_id == current_user.user_id,
        UploadHistory.status == "성공",
    ).order_by(UploadHistory.upload_date.desc(), UploadHistory.id.desc()).first()
    rows = query_user_analysis(
        db,
        current_user.user_id,
        upload_file_id=upload.id if upload else None,
        upload_content_hash=upload.content_hash if upload else None,
    ).order_by(AnalysisResult.final_score.desc()).all()
    recommended_qty_by_item_id = _recommended_qty_by_item_id(
        db,
        [item.item_id for _, item in rows],
    )
    risk_count = sum(analysis.risk_grade == "악성" for analysis, _ in rows)
    aging_count = sum(analysis.risk_grade == "장기" for analysis, _ in rows)
    diagnosed_rows = [
        (analysis, item)
        for analysis, item in rows
        if analysis.ai_diagnosis or analysis.action_plans
    ]
    ai_summary_row = None
    summary_snapshot = None
    summary_scope = "current_account" if upload is None else "selected_upload"
    summary_as_of = None
    if summary_upload:
        ai_summary_row = db.query(UploadAnalysisSummary).filter(
            UploadAnalysisSummary.upload_id == summary_upload.id,
            UploadAnalysisSummary.user_id == current_user.user_id,
        ).first()
        if ai_summary_row:
            summary_as_of = ai_summary_row.generated_at.isoformat() if ai_summary_row.generated_at else None
            if ai_summary_row.summary_data:
                try:
                    stored_summary_data = json.loads(ai_summary_row.summary_data)
                    if isinstance(stored_summary_data, dict) and isinstance(stored_summary_data.get("metrics"), dict):
                        summary_scope = stored_summary_data.get("scope", "selected_upload")
                        summary_snapshot = stored_summary_data["metrics"]
                    elif isinstance(stored_summary_data, dict):
                        summary_scope = "account_active_inventory" if "diagnosed_count" in stored_summary_data else "selected_upload"
                        summary_snapshot = stored_summary_data
                except (json.JSONDecodeError, TypeError):
                    summary_snapshot = None

    if summary_snapshot is None:
        if upload is None:
            summary_snapshot = make_user_summary_input(db, current_user.user_id)
        else:
            summary_snapshot = {
                "total_count": len(rows),
                "inventory_value": round(sum(float(item.stock_qty or 0) * float(item.purchase_price or 0) for _, item in rows)),
                "risk_count": risk_count,
                "aging_count": aging_count,
                "diagnosed_count": len(diagnosed_rows),
            }

    if not summary_upload:
        ai_summary_status = "unavailable"
        ai_summary = "성공한 업로드가 없어 AI 종합진단을 표시할 수 없습니다. 재고 파일을 업로드해주세요."
    elif ai_summary_row and ai_summary_row.status == "complete" and ai_summary_row.summary_text:
        ai_summary_status = "complete"
        ai_summary = ai_summary_row.summary_text
    elif ai_summary_row and ai_summary_row.status == "failed":
        ai_summary_status = "failed"
        ai_summary = "파일 업로드와 재고 분석은 완료됐지만 AI 종합진단을 생성하지 못했습니다. 잠시 후 다시 시도해주세요."
    elif ai_summary_row and ai_summary_row.status == "stale":
        ai_summary_status = "stale"
        ai_summary = (
            "이 누적 진단은 생성 후 재고가 변경되어 최신 상태가 아닙니다. "
            "다음 업로드 후 새 누적 진단이 생성됩니다. "
            f"이전 진단: {ai_summary_row.summary_text or '내용 없음'}"
        )
    elif diagnosed_rows:
        ai_summary_status = "legacy"
        priorities = [
            f"{item.product_name} ({analysis.risk_grade}): {analysis.action_plans or analysis.ai_diagnosis}"
            for analysis, item in diagnosed_rows[:3]
        ]
        ai_summary = (
            f"이전 품목별 진단 {len(diagnosed_rows)}건을 요약했습니다. "
            f"우선 검토할 품목은 {'; '.join(priorities)}입니다."
        )
    else:
        ai_summary_status = "unavailable"
        ai_summary = "이 업로드에는 저장된 AI 종합진단이 없습니다. 신규 업로드부터 파일별 요약이 생성됩니다."
    items = [{
        "item_id": item.item_id,
        "product_name": item.product_name,
        "stock_qty": item.stock_qty,
        "sales_qty": item.sales_qty,
        "purchase_price": float(item.purchase_price or 0),
        "selling_price": float(item.market_price or 0),
        "mock_market_price": float(item.mock_market_price) if item.mock_market_price is not None else None,
        "recommended_price": float(analysis.recommended_price) if analysis.recommended_price is not None else None,
        "received_date": item.inbound_date.isoformat() if item.inbound_date else None,
        "aging_days": analysis.aging_days,
        "storage_days": analysis.aging_days,
        "days_to_sell": analysis.days_to_sell,
        "final_score": float(analysis.final_score or 0),
        "depreciation_rate": float(analysis.fluctuation_rate or 0),
        "inventory_value": float(analysis.inventory_amount or 0),
        "risk_grade": analysis.risk_grade,
        "recommended_qty": recommended_qty_by_item_id.get(item.item_id),
        "action_plans": analysis.action_plans,
        "ai_diagnosis": analysis.ai_diagnosis,
    } for analysis, item in rows]
    return {
        "summary": {
            "total_count": int(summary_snapshot.get("total_count", len(items))),
            "inventory_value": int(summary_snapshot.get("inventory_value", 0)),
            "risk_count": int(summary_snapshot.get("risk_count", risk_count)),
            "aging_count": int(summary_snapshot.get("aging_count", aging_count)),
            "ai_diagnosis_count": int(summary_snapshot.get("diagnosed_count", len(diagnosed_rows))),
            "ai_summary": ai_summary,
            "ai_summary_status": ai_summary_status,
            "scope": summary_scope,
            "as_of": summary_as_of,
            "summary_upload_id": summary_upload.id if summary_upload else None,
        },
        "upload_file_name": upload.file_name if upload else None,
        "summary_source_file_name": summary_upload.file_name if summary_upload else None,
        "items": items,
    }
