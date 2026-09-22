import hashlib
import io
import json

import pandas as pd
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.analysis import analyze_inventory
from app.config import MAX_UPLOAD_ROWS
from app.models import UploadHistory

REQUIRED_COLUMNS = ["상품명", "재고량", "원가", "입고일", "판매가", "판매량"]


def raise_if_duplicate_upload(db: Session, user_id: int, content_hash: str) -> None:
    duplicate = (
        db.query(UploadHistory)
        .filter(
            UploadHistory.user_id == user_id,
            UploadHistory.content_hash == content_hash,
            UploadHistory.status == "성공",
        )
        .first()
    )
    if duplicate:
        raise HTTPException(status_code=409, detail="이미 같은 내용의 엑셀 데이터가 업로드되어 있습니다.")


def make_upload_content_hash(df: pd.DataFrame) -> str:
    normalized_data = df[REQUIRED_COLUMNS].copy()
    normalized_data["입고일"] = normalized_data["입고일"].map(
        lambda value: None if pd.isna(value) else pd.to_datetime(value).date().isoformat()
    )
    records = normalized_data.where(pd.notna(normalized_data), None).to_dict(orient="records")
    serialized_data = json.dumps(records, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized_data.encode("utf-8")).hexdigest()


def parse_and_analyze_upload(contents: bytes, filename: str, csv_encoding: str | None) -> pd.DataFrame:
    if filename.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(contents))
    else:
        df = pd.read_csv(io.BytesIO(contents), encoding=csv_encoding)

    if len(df) == 0:
        raise HTTPException(status_code=400, detail="업로드 파일에 데이터 행이 없습니다.")
    if len(df) > MAX_UPLOAD_ROWS:
        raise HTTPException(status_code=413, detail=f"행 수는 {MAX_UPLOAD_ROWS}개를 초과할 수 없습니다.")

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing_columns:
        raise HTTPException(status_code=400, detail=f"필수 컬럼이 없습니다: {missing_columns}")

    return analyze_inventory(df)
