from datetime import datetime

import pandas as pd
from sqlalchemy.orm import Session

from app.models import AnalysisResult, RawInventory, UploadHistory


def save_inventory_analysis(db: Session, user_id: int, upload_batch_id: str, df: pd.DataFrame) -> None:
    now = datetime.utcnow()
    raw_rows = [
        RawInventory(
            user_id=user_id,
            upload_batch_id=str(upload_batch_id),
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
    db.add_all([
        AnalysisResult(
            item_id=raw_item.item_id,
            sales_velocity=row["sales_speed"],
            aging_days=int(row["storage_days"]),
            days_to_sell=int(min(row["days_to_sell"], 9999)),
            risk_grade=row["risk_grade"],
            inventory_amount=row["inventory_value"],
            final_score=row["final_score"],
            fluctuation_rate=row["depreciation_rate"],
            updated_at=now,
        )
        for raw_item, (_, row) in zip(raw_rows, df.iterrows())
    ])
    db.commit()


def save_upload_history(db: Session, user_id: int, filename: str, file_size: int, status: str, content_hash: str | None = None) -> UploadHistory:
    history = UploadHistory(user_id=user_id, file_name=filename, size=file_size, status=status, content_hash=content_hash)
    db.add(history)
    db.commit()
    db.refresh(history)
    return history


def query_user_analysis(db: Session, user_id: int):
    return db.query(AnalysisResult, RawInventory).join(
        RawInventory, AnalysisResult.item_id == RawInventory.item_id
    ).filter(RawInventory.user_id == user_id)
