from datetime import datetime

import pandas as pd
from sqlalchemy.orm import Session

from app.models import AnalysisResult, RawInventory, UploadHistory


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


def query_user_analysis(db: Session, user_id: int):
    return (
        db.query(AnalysisResult, RawInventory)
        .join(RawInventory, AnalysisResult.item_id == RawInventory.item_id)
        .filter(RawInventory.user_id == user_id)
    )
