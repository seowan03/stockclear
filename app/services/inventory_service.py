from datetime import datetime

import numpy as np
import pandas as pd
from fastapi import HTTPException
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.analysis import analyze_inventory
from app.models import AnalysisResult, RawInventory, UploadAnalysisSummary, UploadHistory, User
from app.schemas import InventoryGridBatchUpdate
from app.services.daily_inventory_service import replace_daily_inventory_metrics
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
    db.query(User).filter(User.user_id == user_id).with_for_update().first()

    rows_by_key = {}
    for _, row in df.iterrows():
        product_name = str(row["product_name"]).strip()
        rows_by_key[product_name] = row

    existing_by_key = {}
    existing_candidates = {}
    requested_names = set(rows_by_key)
    product_names = list(requested_names)
    for offset in range(0, len(product_names), 500):
        name_batch = product_names[offset:offset + 500]
        candidates = db.query(RawInventory).filter(
            RawInventory.user_id == user_id,
            func.trim(RawInventory.product_name).in_(name_batch),
        ).order_by(RawInventory.item_id.desc()).all()
        for candidate in candidates:
            product_name = str(candidate.product_name or "").strip()
            if product_name in requested_names:
                existing_candidates.setdefault(product_name, []).append(candidate)

    for product_name, candidates in existing_candidates.items():
        candidates.sort(key=lambda item: (bool(item.is_deleted), -item.item_id))
        existing_by_key[product_name] = candidates[0]
        for duplicate in candidates[1:]:
            if not duplicate.is_deleted:
                duplicate.is_deleted = True

    saved_rows = []
    for product_name, row in rows_by_key.items():
        raw_row = existing_by_key.get(product_name)
        if raw_row is None:
            raw_row = RawInventory(
                user_id=user_id,
                created_at=now,
            )
            db.add(raw_row)

        raw_row.upload_batch_id = str(upload_batch_id)
        raw_row.upload_file_id = upload_file_id
        raw_row.product_name = product_name
        raw_row.stock_qty = int(row["stock_qty"])
        raw_row.purchase_price = row["purchase_price"]
        raw_row.market_price = row["selling_price"]
        raw_row.mock_market_price = generate_mock_market_price(row["selling_price"], price_rng)
        raw_row.inbound_date = pd.to_datetime(row["received_date"]).date()
        raw_row.sales_qty = int(row["sales_qty"])
        raw_row.is_deleted = False
        raw_row.version = (raw_row.version or 0) + 1 if raw_row.item_id else 1
        raw_row.edited_at = None
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
        replace_daily_inventory_metrics(
            db,
            user_id,
            raw_row.item_id,
            raw_row.inbound_date,
            raw_row.market_price,
            raw_row.stock_qty,
        )


def update_inventory_grid(db: Session, user_id: int, payload: InventoryGridBatchUpdate) -> list[dict]:
    db.query(User).filter(User.user_id == user_id).with_for_update().first()
    edits = payload.items
    item_ids = [edit.item_id for edit in edits]
    if len(set(item_ids)) != len(item_ids):
        raise HTTPException(status_code=409, detail="같은 품목이 요청에 중복되어 있습니다.")
    names = [edit.product_name for edit in edits]
    if len(set(names)) != len(names):
        raise HTTPException(status_code=409, detail="상품명이 요청에 중복되어 있습니다.")

    rows = db.query(RawInventory).filter(
        RawInventory.user_id == user_id,
        RawInventory.item_id.in_(item_ids),
        RawInventory.is_deleted.is_(False),
    ).all()
    by_id = {row.item_id: row for row in rows}
    if len(by_id) != len(edits):
        raise HTTPException(status_code=404, detail="수정할 재고를 찾을 수 없습니다.")
    if any(by_id[edit.item_id].version != edit.version for edit in edits):
        raise HTTPException(status_code=409, detail="재고가 변경되었습니다. 새로고침 후 다시 수정해 주세요.")

    conflicts = db.query(RawInventory.item_id).filter(
        RawInventory.user_id == user_id,
        RawInventory.is_deleted.is_(False),
        RawInventory.item_id.notin_(item_ids),
        func.trim(RawInventory.product_name).in_(names),
    ).first()
    if conflicts:
        raise HTTPException(status_code=409, detail="동일한 상품명이 이미 있습니다.")

    analyzed = analyze_inventory(pd.DataFrame([{
        "상품명": edit.product_name,
        "재고량": edit.stock_qty,
        "원가": float(edit.purchase_price),
        "입고일": edit.received_date.isoformat(),
        "판매가": float(edit.selling_price),
        "판매량": edit.sales_qty,
    } for edit in edits]))
    now = datetime.utcnow()
    results = []
    for edit, (_, values) in zip(edits, analyzed.iterrows()):
        current = by_id[edit.item_id]
        price_changed = current.market_price != edit.selling_price
        updated = db.query(RawInventory).filter(
            RawInventory.item_id == edit.item_id,
            RawInventory.user_id == user_id,
            RawInventory.is_deleted.is_(False),
            RawInventory.version == edit.version,
        ).update({
            RawInventory.product_name: edit.product_name,
            RawInventory.stock_qty: edit.stock_qty,
            RawInventory.purchase_price: edit.purchase_price,
            RawInventory.inbound_date: edit.received_date,
            RawInventory.market_price: edit.selling_price,
            RawInventory.sales_qty: edit.sales_qty,
            RawInventory.mock_market_price: generate_mock_market_price(edit.selling_price) if price_changed else current.mock_market_price,
            RawInventory.version: edit.version + 1,
            RawInventory.edited_at: now,
        }, synchronize_session=False)
        if updated != 1:
            raise HTTPException(status_code=409, detail="재고가 변경되었습니다. 새로고침 후 다시 수정해 주세요.")

        analysis = db.query(AnalysisResult).filter(AnalysisResult.item_id == edit.item_id).first()
        if analysis is None:
            analysis = AnalysisResult(item_id=edit.item_id)
            db.add(analysis)
        analysis.sales_velocity = float(values["sales_speed"])
        analysis.aging_days = int(values["storage_days"])
        analysis.days_to_sell = int(min(values["days_to_sell"], 9999))
        analysis.risk_grade = values["risk_grade"]
        analysis.inventory_amount = values["inventory_value"]
        analysis.final_score = float(values["final_score"])
        analysis.fluctuation_rate = float(values["depreciation_rate"])
        analysis.ai_diagnosis = None
        analysis.action_plans = None
        analysis.recommended_price = None
        analysis.updated_at = now
        replace_daily_inventory_metrics(
            db,
            user_id,
            edit.item_id,
            edit.received_date,
            edit.selling_price,
            edit.stock_qty,
        )
        results.append({"item_id": edit.item_id, "version": edit.version + 1})

    db.query(UploadAnalysisSummary).filter(
        UploadAnalysisSummary.user_id == user_id,
        UploadAnalysisSummary.status == "complete",
    ).update({UploadAnalysisSummary.status: "stale"}, synchronize_session=False)
    return results


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
        if grade == "악성":
            risk_count += 1
        if grade == "장기":
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
