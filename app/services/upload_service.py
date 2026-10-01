import hashlib
import io
import json
import math

import pandas as pd
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.analysis import analyze_inventory
from app.config import MAX_UPLOAD_ROWS
from app.models import UploadHistory

REQUIRED_COLUMNS = ["상품명", "재고량", "원가", "입고일", "판매가", "판매량"]


def raise_if_duplicate_upload(db: Session, user_id: int, content_hash: str) -> None:
    duplicate = db.query(UploadHistory).filter(
        UploadHistory.user_id == user_id,
        UploadHistory.content_hash == content_hash,
        UploadHistory.status == "성공",
    ).first()
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


def validate_upload_dataframe(df: pd.DataFrame) -> None:
    """
    행별 수치, 문자, 날짜 유효성을 정밀 검증하고
    오류 발생 시 행 번호와 컬럼명을 명시하여 400 에러를 던짐
    """
    errors = []

    for idx, row in df.iterrows():
        row_num = idx + 2  # 엑셀 헤더 감안 (1행: 컬럼명, 2행: 첫번째 데이터)

        # 1. 필수 문자열 (상품명) 검증
        product_name = str(row.get("상품명", "")).strip()
        if not product_name or product_name.lower() in ["nan", "none", "null"]:
            errors.append(f"{row_num}행 [상품명]: 필수 입력 항목입니다.")

        # 2. 수치형 컬럼 검증 (재고량, 원가, 판매가, 판매량)
        numeric_cols = {
            "재고량": int,
            "원가": float,
            "판매가": float,
            "판매량": int,
        }

        for col, dtype in numeric_cols.items():
            val = row.get(col)

            # 빈 값 / NaN 검증
            if pd.isna(val) or str(val).strip() == "":
                errors.append(f"{row_num}행 [{col}]: 값이 비어 있습니다.")
                continue

            # 숫자 변환, 음수 및 무한대(Inf) 검증
            try:
                num_val = dtype(val)
                if math.isinf(num_val):
                    errors.append(f"{row_num}행 [{col}]: 유효하지 않은 숫자(Inf)입니다.")
                    continue
                if num_val < 0:
                    errors.append(f"{row_num}행 [{col}]: 음수 값({num_val})은 허용되지 않습니다.")
            except (ValueError, TypeError):
                errors.append(f"{row_num}행 [{col}]: 올바른 숫자 형식이 아닙니다 ('{val}').")

        # 3. 입고일 날짜 포맷 검증
        stock_date = row.get("입고일")
        if pd.notna(stock_date) and str(stock_date).strip() not in ["", "nan", "None"]:
            try:
                parsed_date = pd.to_datetime(stock_date).date()
                if parsed_date > pd.Timestamp.today().date():
                    errors.append(f"{row_num}행 [입고일]: 미래 날짜는 입력할 수 없습니다.")
            except Exception:
                errors.append(f"{row_num}행 [입고일]: 올바른 날짜 형식이 아닙니다 ('{stock_date}').")

    # 에러 모음이 존재할 경우 400 Exception 발생
    if errors:
        detailed_msg = " / ".join(errors[:20])
        if len(errors) > 20:
            detailed_msg += f" 외 {len(errors) - 20}건"
        raise HTTPException(status_code=400, detail=f"데이터 검증 실패: {detailed_msg}")
    

def parse_and_analyze_upload(contents: bytes, filename: str, csv_encoding: str | None) -> pd.DataFrame:
    if filename.lower().endswith(".xlsx"):
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
    validate_upload_dataframe(df)
    df["상품명"] = df["상품명"].astype(str).str.strip()
    return analyze_inventory(df)
