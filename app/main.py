import io
from collections import Counter
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import RawInventory, User
from app.router import raise_if_duplicate_upload


# 엑셀/CSV에서 읽은 pandas 값을 DB에 넣기 좋은 기본 Python 타입으로 변환
def parse_int(value):
    if pd.isna(value):
        return None
    return int(value)


def parse_price(value):
    if pd.isna(value):
        return None
    return Decimal(str(value))


def parse_date(value):
    if pd.isna(value):
        return None
    return pd.to_datetime(value).date()


# 한 행의 핵심 컬럼 값을 튜플로 묶어 중복 업로드 비교 기준으로 사용
def make_inventory_signature(product_name, stock_qty, purchase_price, inbound_date, market_price, sales_qty):
    return (
        None if pd.isna(product_name) else str(product_name),
        parse_int(stock_qty),
        parse_price(purchase_price),
        parse_date(inbound_date),
        parse_price(market_price),
        parse_int(sales_qty),
    )


# 로그인 기능이 아직 연결되지 않았으므로 업로드 저장에 사용할 기본 user_id 확보
def get_upload_user_id(db: Session):
    user = db.query(User).order_by(User.user_id).first()
    if user:
        return user.user_id

    user = User(
        username="upload_user",
        email="upload_user@stockclear.local",
        password_hash="upload_user",
        created_at=datetime.now(),
    )
    db.add(user)
    db.flush()
    return user.user_id


# DB 테이블을 생성하고, 기존 raw_inventory 테이블에 sales_qty 컬럼이 없으면 보강
def ensure_database_schema():
    Base.metadata.create_all(bind=engine)

    inspector = inspect(engine)
    raw_inventory_columns = {
        column["name"] for column in inspector.get_columns("raw_inventory")
    }

    if "sales_qty" not in raw_inventory_columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE raw_inventory ADD COLUMN sales_qty INT NULL")
            )

# ---------------------------------------------------------
# 아직 작업 안 한 외부 모듈 임포트는 주석 처리 해둡니다.
# ---------------------------------------------------------
# from analysis import analyze_inventory
# from schemas import UploadResponse


app = FastAPI(title="StockClear Backend", version="1.0")

ensure_database_schema()

# -------------------- CORS 설정 --------------------
origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- 루트 기본 접속 테스트 --------------------
@app.get("/")
def read_root():
    return FileResponse("static/upload.html")


# -------------------- 엑셀 업로드 API (임시) --------------------
# response_model=UploadResponse 부분은 schemas 작업 전이므로 임시 제거했습니다.
@app.post("/api/upload")
async def upload_and_parse_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):

    if not file.filename.endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(
            status_code=400,
            detail="엑셀 파일(.xlsx, .xls) 또는 CSV 파일만 업로드 가능합니다."
        )

    try:
        contents = await file.read()

        if file.filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(contents))
        else:
            df = pd.read_csv(io.BytesIO(contents))

        required_columns = ["상품명", "재고량", "원가", "입고일", "판매가", "판매량"]
        missing_columns = [col for col in required_columns if col not in df.columns]

        if missing_columns:
            raise HTTPException(
                status_code=400,
                detail=f"필수 컬럼이 없습니다: {missing_columns}"
            )

        # analysis 작업 전이므로 분석 함수(analyze_inventory) 호출 부분은 주석 처리합니다.
        # df = analyze_inventory(df)

        # 파일명은 비교하지 않고, 엑셀 내부 행 데이터가 완전히 같은지만 확인
        upload_signature = Counter(
            make_inventory_signature(
                row["상품명"],
                row["재고량"],
                row["원가"],
                row["입고일"],
                row["판매가"],
                row["판매량"],
            )
            for _, row in df.iterrows()
        )
        # 같은 내용의 업로드 묶음이 이미 있으면 409 예외 발생
        raise_if_duplicate_upload(db, upload_signature)

        upload_batch_id = str(uuid4())
        upload_user_id = get_upload_user_id(db)
        now = datetime.now()
        inventory_items = []

        # 중복 검사를 통과한 데이터만 raw_inventory 테이블에 저장
        for signature, count in upload_signature.items():
            product_name, stock_qty, purchase_price, inbound_date, market_price, sales_qty = signature
            for _ in range(count):
                inventory_items.append(
                    RawInventory(
                        user_id=upload_user_id,
                        upload_batch_id=upload_batch_id,
                        product_name=product_name,
                        stock_qty=stock_qty,
                        purchase_price=purchase_price,
                        market_price=market_price,
                        sales_qty=sales_qty,
                        inbound_date=inbound_date,
                        created_at=now,
                    )
                )

        db.add_all(inventory_items)
        db.commit()

        parsed_data = df.to_dict(orient="records")

        return {
            "status": "success",
            "filename": file.filename,
            "upload_batch_id": upload_batch_id,
            "total_rows": len(parsed_data),
            "saved_rows": len(inventory_items),
            "data_preview": parsed_data
        }

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"엑셀 파싱 중 에러 발생: {str(e)}"
        )


# -------------------- 정적 HTML/CSS 페이지 연결 --------------------
# 위의 명시적 라우트("/", "/api/...")에 안 걸린 나머지 경로를
# static 폴더에서 파일명 그대로 서빙 (dashboard.html, style.css 등 상대경로 링크와 호환)
app.mount("/", StaticFiles(directory="static"), name="static")