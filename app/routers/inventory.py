import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import RISK_GRADE_META
from app.database import get_db
from app.models import AnalysisResult, RawInventory, StrategyAction, UploadHistory, User
from app.schemas import InventoryInput
from app.security import get_current_user
from app.services.inventory_service import analyze_inventory_values, query_user_analysis

router = APIRouter(tags=["inventory"])


def _create_analysis_row(item_id: int, calculated: dict) -> AnalysisResult:
    return AnalysisResult(
        item_id=item_id,
        sales_velocity=float(calculated["sales_speed"]),
        aging_days=int(calculated["storage_days"]),
        days_to_sell=int(min(calculated["days_to_sell"], 9999)),
        risk_grade=calculated["risk_grade"],
        inventory_amount=calculated["inventory_value"],
        final_score=float(calculated["final_score"]),
        fluctuation_rate=float(calculated["depreciation_rate"]),
        updated_at=datetime.now(timezone.utc),
    )


@router.post("/api/inventory", status_code=201)
def create_inventory_item(data: InventoryInput, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    calculated = analyze_inventory_values(**data.model_dump())
    item = RawInventory(
        user_id=current_user.user_id,
        upload_batch_id="manual",
        product_name=data.product_name,
        stock_qty=data.stock_qty,
        purchase_price=data.purchase_price,
        market_price=data.selling_price,
        inbound_date=data.received_date,
        created_at=datetime.now(timezone.utc),
        sales_qty=data.sales_qty,
    )
    db.add(item)
    db.flush()
    db.add(_create_analysis_row(item.item_id, calculated))
    db.commit()
    return {"status": "created", "item_id": item.item_id}


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
        if analysis.risk_grade in ("위험", "처분 권장"):
            risk_count += 1
        if analysis.aging_days >= 60:
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
    return {"upload_file_name": upload.file_name if upload else None, "items": [{
        "item_id": item.item_id,
        "product_name": item.product_name,
        "stock_qty": item.stock_qty,
        "purchase_price": float(item.purchase_price or 0),
        "selling_price": float(item.market_price or 0),
        "received_date": item.inbound_date.isoformat() if item.inbound_date else None,
        "sales_speed": float(analysis.sales_velocity or 0),
        "sales_qty": item.sales_qty,
        "storage_days": analysis.aging_days,
        "days_to_sell": analysis.days_to_sell,
        "final_score": float(analysis.final_score or 0),
        "depreciation_rate": float(analysis.fluctuation_rate or 0),
        "inventory_value": float(analysis.inventory_amount or 0),
        "risk_grade": analysis.risk_grade,
        "action_plans": analysis.action_plans,
        "ai_diagnosis": analysis.ai_diagnosis,
    } for analysis, item in rows]}


@router.get("/api/inventory/trash")
def list_deleted_inventory(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = query_user_analysis(db, current_user.user_id, include_deleted=True).filter(
        RawInventory.is_deleted.is_(True)
    ).order_by(AnalysisResult.final_score.desc()).all()
    return {"items": [{
        "item_id": item.item_id,
        "product_name": item.product_name,
        "stock_qty": item.stock_qty,
        "risk_grade": analysis.risk_grade,
    } for analysis, item in rows]}


@router.delete("/api/inventory/{item_id}")
def move_inventory_to_trash(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.query(RawInventory).filter(
        RawInventory.item_id == item_id,
        RawInventory.user_id == current_user.user_id,
        RawInventory.is_deleted.is_(False),
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="해당 재고를 찾을 수 없습니다.")
    item.is_deleted = True
    db.commit()
    return {"status": "deleted", "item_id": item_id}


@router.post("/api/inventory/{item_id}/restore")
def restore_inventory(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.query(RawInventory).filter(
        RawInventory.item_id == item_id,
        RawInventory.user_id == current_user.user_id,
        RawInventory.is_deleted.is_(True),
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="휴지통에서 재고를 찾을 수 없습니다.")
    item.is_deleted = False
    db.commit()
    return {"status": "restored", "item_id": item_id}


@router.delete("/api/inventory/{item_id}/permanent")
def permanently_delete_inventory(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = db.query(RawInventory).filter(
        RawInventory.item_id == item_id,
        RawInventory.user_id == current_user.user_id,
        RawInventory.is_deleted.is_(True),
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="휴지통에서 재고를 찾을 수 없습니다.")
    db.query(AnalysisResult).filter(AnalysisResult.item_id == item_id).delete()
    db.delete(item)
    db.commit()
    return {"status": "permanently_deleted", "item_id": item_id}


@router.delete("/api/inventory/trash/empty")
def empty_inventory_trash(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    deleted_ids = [row.item_id for row in db.query(RawInventory.item_id).filter(
        RawInventory.user_id == current_user.user_id,
        RawInventory.is_deleted.is_(True),
    ).all()]
    if deleted_ids:
        db.query(AnalysisResult).filter(AnalysisResult.item_id.in_(deleted_ids)).delete(synchronize_session=False)
        db.query(RawInventory).filter(RawInventory.item_id.in_(deleted_ids)).delete(synchronize_session=False)
        db.commit()
    return {"status": "emptied", "deleted_count": len(deleted_ids)}


@router.get("/api/inventory/{item_id}")
def get_inventory_item(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = query_user_analysis(db, current_user.user_id).filter(RawInventory.item_id == item_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="해당 재고를 찾을 수 없습니다.")
    analysis, item = row
    return {"item_id": item.item_id, "product_name": item.product_name, "stock_qty": item.stock_qty, "aging_days": analysis.aging_days, "days_to_sell": analysis.days_to_sell, "risk_grade": analysis.risk_grade, "ai_diagnosis": analysis.ai_diagnosis}


@router.get("/api/strategy")
def get_strategy(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = db.query(AnalysisResult.risk_grade, func.count(AnalysisResult.result_id)).join(RawInventory, AnalysisResult.item_id == RawInventory.item_id).filter(RawInventory.user_id == current_user.user_id, RawInventory.is_deleted.is_(False)).group_by(AnalysisResult.risk_grade).all()
    active_items = query_user_analysis(db, current_user.user_id)
    order_count = active_items.filter(AnalysisResult.risk_grade.in_(("위험", "처분 권장"))).count()
    promotion_count = active_items.filter(AnalysisResult.aging_days >= 60).count()
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
        query = query.filter(AnalysisResult.risk_grade.in_(("위험", "처분 권장")))
    else:
        query = query.filter(RawInventory.is_deleted.is_(False), AnalysisResult.aging_days >= 60)
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
    rows = query_user_analysis(
        db,
        current_user.user_id,
        upload_file_id=upload.id if upload else None,
        upload_content_hash=upload.content_hash if upload else None,
    ).order_by(AnalysisResult.final_score.desc()).all()
    risk_count = sum(analysis.risk_grade in ("위험", "처분 권장") for analysis, _ in rows)
    aging_count = sum(analysis.aging_days >= 60 for analysis, _ in rows)
    items = [{"item_id": item.item_id, "product_name": item.product_name, "stock_qty": item.stock_qty, "aging_days": analysis.aging_days, "risk_grade": analysis.risk_grade, "action_plans": analysis.action_plans, "ai_diagnosis": analysis.ai_diagnosis} for analysis, item in rows]
    return {
        "summary": {"total_count": len(items), "risk_count": risk_count, "aging_count": aging_count},
        "upload_file_name": upload.file_name if upload else None,
        "items": items,
    }
