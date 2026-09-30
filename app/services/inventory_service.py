from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models import AnalysisResult, RawInventory, UploadAnalysisSummary, UploadHistory
from app.services.mock_market_price import generate_mock_market_price


def save_inventory_analysis(
    db: Session,
    user_id: int,
    upload_batch_id: str,
    df: pd.DataFrame,
    upload_file_id: int | None = None,
    rng: np.random.Generator | None = None,
) -> None:
    now = datetime.utcnow()
    price_rng = rng if rng is not None else np.random.default_rng()

    rows_by_key = {}
    for _, row in df.iterrows():
        product_name = str(row["product_name"]).strip()
        inbound_date = pd.to_datetime(row["received_date"]).date()
        rows_by_key[(product_name, inbound_date)] = row

    existing_by_key = {}
    existing_candidates = {}
    requested_keys = set(rows_by_key)
    inbound_dates = list({inbound_date for _, inbound_date in requested_keys})
    for offset in range(0, len(inbound_dates), 500):
        date_batch = inbound_dates[offset:offset + 500]
        candidates = db.query(RawInventory).filter(
            RawInventory.user_id == user_id,
            RawInventory.inbound_date.in_(date_batch),
        ).order_by(RawInventory.item_id).all()
        for candidate in candidates:
            key = (str(candidate.product_name or "").strip(), candidate.inbound_date)
            if key in requested_keys:
                existing_candidates.setdefault(key, []).append(candidate)

    for key, candidates in existing_candidates.items():
        candidates.sort(key=lambda item: (bool(item.is_deleted), item.item_id))
        existing_by_key[key] = candidates[0]
        for duplicate in candidates[1:]:
            if not duplicate.is_deleted:
                duplicate.is_deleted = True

    saved_rows = []
    for key, row in rows_by_key.items():
        raw_row = existing_by_key.get(key)
        if raw_row is None:
            raw_row = RawInventory(
                user_id=user_id,
                created_at=now,
            )
            db.add(raw_row)

        raw_row.upload_batch_id = str(upload_batch_id)
        raw_row.upload_file_id = upload_file_id
        raw_row.product_name = key[0]
        raw_row.stock_qty = int(row["stock_qty"])
        raw_row.purchase_price = row["purchase_price"]
        raw_row.market_price = row["selling_price"]
        raw_row.mock_market_price = generate_mock_market_price(row["selling_price"], price_rng)
        raw_row.inbound_date = key[1]
        raw_row.sales_qty = int(row["sales_qty"])
        raw_row.is_deleted = False
        saved_rows.append((raw_row, row))

    db.flush()

    analysis_by_item_id = {}
    item_ids = [raw_row.item_id for raw_row, _ in saved_rows]
    for offset in range(0, len(item_ids), 500):
        item_id_batch = item_ids[offset:offset + 500]
        analyses = db.query(AnalysisResult).filter(
            AnalysisResult.item_id.in_(item_id_batch),
        ).order_by(AnalysisResult.result_id).all()
        for analysis in analyses:
            analysis_by_item_id.setdefault(analysis.item_id, analysis)

    for raw_row, row in saved_rows:
        analysis = analysis_by_item_id.get(raw_row.item_id)
        if analysis is None:
            analysis = AnalysisResult(item_id=raw_row.item_id)
            db.add(analysis)
        analysis.sales_velocity = row["sales_speed"]
        analysis.aging_days = int(row["storage_days"])
        analysis.days_to_sell = int(min(row["days_to_sell"], 9999))
        analysis.risk_grade = row["risk_grade"]
        analysis.inventory_amount = row["inventory_value"]
        analysis.final_score = row["final_score"]
        analysis.fluctuation_rate = row["depreciation_rate"]
        analysis.ai_diagnosis = None
        analysis.action_plans = None
        analysis.recommended_price = None
        analysis.updated_at = now


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
