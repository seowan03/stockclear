from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import RISK_GRADE_META
from app.database import get_db
from app.models import AnalysisResult, RawInventory, User
from app.security import get_current_user
from app.services.inventory_service import query_user_analysis

router = APIRouter(tags=["inventory"])


@router.get("/api/dashboard")
def get_dashboard(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = query_user_analysis(db, current_user.user_id).all()
    if not rows:
        return {"total_sku": 0, "risk_count": 0, "aging_count": 0, "monthly_saving": 0, "grades": [], "risk_items": []}

    grade_counts: dict[str, int] = {}
    risk_count = 0
    aging_count = 0
    monthly_saving = 0.0
    for analysis, _ in rows:
        grade_counts[analysis.risk_grade] = grade_counts.get(analysis.risk_grade, 0) + 1
        if analysis.risk_grade in ("위험", "처분 권장"):
            risk_count += 1
            monthly_saving += float(analysis.inventory_amount or 0) * 0.1
        if analysis.aging_days >= 60:
            aging_count += 1

    risk_items = sorted(
        ({"product_name": item.product_name, "final_score": analysis.final_score} for analysis, item in rows),
        key=lambda value: value["final_score"],
        reverse=True,
    )[:5]
    return {
        "total_sku": len(rows),
        "risk_count": risk_count,
        "aging_count": aging_count,
        "monthly_saving": round(monthly_saving),
        "grades": [
            {"name": name, "count": count, "color": RISK_GRADE_META.get(name, {}).get("color", "#64748b")}
            for name, count in grade_counts.items()
        ],
        "risk_items": risk_items,
    }


@router.get("/api/inventory")
def list_inventory(search: str = "", status: str = "", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = query_user_analysis(db, current_user.user_id)
    if search:
        query = query.filter(RawInventory.product_name.contains(search))
    if status:
        query = query.filter(AnalysisResult.risk_grade == status)
    rows = query.order_by(AnalysisResult.final_score.desc()).all()
    return {
        "items": [
            {
                "item_id": item.item_id,
                "product_name": item.product_name,
                "stock_qty": item.stock_qty,
                "aging_days": analysis.aging_days,
                "days_to_sell": analysis.days_to_sell,
                "risk_grade": analysis.risk_grade,
                "action_plans": analysis.action_plans,
            }
            for analysis, item in rows
        ]
    }


@router.get("/api/inventory/{item_id}")
def get_inventory_item(item_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = query_user_analysis(db, current_user.user_id).filter(RawInventory.item_id == item_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="해당 재고를 찾을 수 없습니다.")
    analysis, item = row
    return {
        "item_id": item.item_id,
        "product_name": item.product_name,
        "stock_qty": item.stock_qty,
        "aging_days": analysis.aging_days,
        "days_to_sell": analysis.days_to_sell,
        "risk_grade": analysis.risk_grade,
        "ai_diagnosis": analysis.ai_diagnosis,
    }


@router.get("/api/strategy")
def get_strategy(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = (
        db.query(AnalysisResult.risk_grade, func.count(AnalysisResult.result_id))
        .join(RawInventory, AnalysisResult.item_id == RawInventory.item_id)
        .filter(RawInventory.user_id == current_user.user_id)
        .group_by(AnalysisResult.risk_grade)
        .all()
    )
    return {
        "groups": [
            {
                "type": grade,
                "title": RISK_GRADE_META.get(grade, {}).get("title", grade),
                "summary": RISK_GRADE_META.get(grade, {}).get("summary", ""),
                "count": count,
            }
            for grade, count in rows
        ]
    }


@router.get("/api/export")
def get_export(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = query_user_analysis(db, current_user.user_id).order_by(AnalysisResult.final_score.desc()).all()
    items = [
        {
            "item_id": item.item_id,
            "product_name": item.product_name,
            "stock_qty": item.stock_qty,
            "aging_days": analysis.aging_days,
            "risk_grade": analysis.risk_grade,
            "action_plans": analysis.action_plans,
        }
        for analysis, item in rows
    ]
    return {"summary": f"총 {len(items)}개 품목의 재고 분석 리포트입니다.", "items": items}
