from datetime import datetime

import pandas as pd
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models import AnalysisResult, RawInventory, UploadAnalysisSummary, UploadHistory


def save_inventory_analysis(
    db: Session,
    user_id: int,
    upload_batch_id: str,
    df: pd.DataFrame,
    upload_file_id: int | None = None,
) -> None:
    now = datetime.utcnow()
    raw_rows = [
        RawInventory(
            user_id=user_id,
            upload_batch_id=str(upload_batch_id),
            upload_file_id=upload_file_id,
            product_name=row["product_name"],
            stock_qty=int(row["stock_qty"]),
            purchase_price=row["purchase_price"],
            market_price=row["selling_price"],
            inbound_date=row["received_date"].date(),
            created_at=now,
            sales_qty=int(row["sales_qty"]),
        )
        for _, row in df.iterrows()
    ]
    db.add_all(raw_rows)
    db.flush()

    # Commit은 업로드 라우터에서 이력 저장까지 끝난 뒤 한 번만 수행한다.
    db.add_all(
        [
            AnalysisResult(
                item_id=raw_row.item_id,
                sales_velocity=row["sales_speed"],
                aging_days=int(row["storage_days"]),
                days_to_sell=int(min(row["days_to_sell"], 9999)),
                risk_grade=row["risk_grade"],
                inventory_amount=row["inventory_value"],
                final_score=row["final_score"],
                fluctuation_rate=row["depreciation_rate"],
                updated_at=now,
            )
            for raw_row, (_, row) in zip(raw_rows, df.iterrows())
        ]
    )


def save_upload_history(
    db: Session,
    user_id: int,
    filename: str,
    file_size: int,
    status: str,
    content_hash: str | None = None,
) -> UploadHistory:
    history = UploadHistory(
        user_id=user_id,
        file_name=filename,
        size=file_size,
        status=status,
        content_hash=content_hash,
    )
    db.add(history)
    # 호출자가 같은 트랜잭션 안에서 다른 저장 작업과 함께 commit한다.
    db.flush()
    return history


def query_user_analysis(
    db: Session,
    user_id: int,
    include_deleted: bool = False,
    upload_file_id: int | None = None,
    upload_content_hash: str | None = None,
):
    query = (
        db.query(AnalysisResult, RawInventory)
        .join(RawInventory, AnalysisResult.item_id == RawInventory.item_id)
        .filter(RawInventory.user_id == user_id)
    )
    if not include_deleted:
        query = query.filter(RawInventory.is_deleted.is_(False))
    if upload_file_id is not None:
        upload_filter = RawInventory.upload_file_id == upload_file_id
        if upload_content_hash:
            upload_filter = or_(
                upload_filter,
                and_(
                    RawInventory.upload_file_id.is_(None),
                    RawInventory.upload_batch_id == upload_content_hash,
                ),
            )
        query = query.filter(upload_filter)
    return query


def make_user_summary_input(db: Session, user_id: int) -> dict:
    rows = query_user_analysis(db, user_id).all()
    risk_grade_counts: dict[str, int] = {}
    risk_count = aging_count = diagnosed_count = 0
    inventory_value = 0.0

    for analysis, _ in rows:
        grade = analysis.risk_grade or "미분류"
        risk_grade_counts[grade] = risk_grade_counts.get(grade, 0) + 1
        if grade in ("위험", "처분 권장"):
            risk_count += 1
        if (analysis.aging_days or 0) >= 60:
            aging_count += 1
        if analysis.ai_diagnosis or analysis.action_plans:
            diagnosed_count += 1
        inventory_value += float(analysis.inventory_amount or 0)

    top_rows = sorted(
        rows,
        key=lambda pair: float(pair[0].final_score or 0),
        reverse=True,
    )[:3]
    return {
        "scope": "account_active_inventory",
        "total_count": len(rows),
        "inventory_value": round(inventory_value),
        "risk_count": risk_count,
        "aging_count": aging_count,
        "risk_grade_counts": risk_grade_counts,
        "diagnosed_count": diagnosed_count,
        "top_risk_items": [
            {
                "risk_grade": analysis.risk_grade or "미분류",
                "risk_score": round(float(analysis.final_score or 0), 1),
                "storage_days": analysis.aging_days or 0,
                "days_to_sell": analysis.days_to_sell or 0,
                "depreciation_rate": round(float(analysis.fluctuation_rate or 0), 1),
            }
            for analysis, _ in top_rows
        ],
    }


def mark_latest_upload_summary_stale(db: Session, user_id: int) -> None:
    latest = db.query(UploadAnalysisSummary).filter(
        UploadAnalysisSummary.user_id == user_id
    ).order_by(
        UploadAnalysisSummary.generated_at.desc(),
        UploadAnalysisSummary.summary_id.desc(),
    ).first()
    if latest and latest.status == "complete":
        latest.status = "stale"
