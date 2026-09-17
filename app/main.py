from collections import Counter
from datetime import datetime
from decimal import Decimal
import io
from uuid import uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import pandas as pd
from pydantic import BaseModel
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from app.database import Base, engine, ensure_upload_files_user_id_column, get_db
from app.models import RawInventory, UploadHistory, User
from app.router import raise_if_duplicate_upload

SESSION_COOKIE_NAME = "session_user"

app = FastAPI(title="StockClear Backend", version="1.0")


# -------------------- 파싱 및 데이터 유틸 함수 --------------------
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


# DB 테이블 생성 및 스키마 검증
def ensure_database_schema():
    Base.metadata.create_all(bind=engine)
    ensure_upload_files_user_id_column()

    inspector = inspect(engine)
    raw_inventory_columns = {
        column["name"] for column in inspector.get_columns("raw_inventory")
    }

    if "sales_qty" not in raw_inventory_columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE raw_inventory ADD COLUMN sales_qty INT NULL")
            )


# -------------------- 앱 시작 시 초기화 --------------------
@app.on_event("startup")
def on_startup():
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


# -------------------- 로그인/인증 스키마 및 유틸 --------------------
class SignupRequest(BaseModel):
    username: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not user_id:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    user = db.query(User).filter(User.user_id == int(user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return user


def _save_history(db: Session, user_id: int, filename: str, file_size: int, status: str) -> None:
    db.add(UploadHistory(user_id=user_id, file_name=filename, size=file_size, status=status))
    db.commit()


# -------------------- Auth API --------------------
@app.post("/api/auth/signup")
def signup(data: SignupRequest, response: Response, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="이미 가입된 이메일입니다.")

    user = User(
        username=data.username,
        email=data.email,
        password_hash=generate_password_hash(data.password),
        created_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    response.set_cookie(SESSION_COOKIE_NAME, str(user.user_id), httponly=True, samesite="lax")
    return {"status": "success", "user_id": user.user_id, "username": user.username}


@app.post("/api/auth/login")
def login(data: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not user.password_hash or not check_password_hash(user.password_hash, data.password):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")

    response.set_cookie(SESSION_COOKIE_NAME, str(user.user_id), httponly=True, samesite="lax")
    return {"status": "success", "user_id": user.user_id, "username": user.username}


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"status": "success"}


@app.get("/api/auth/me")
def me(request: Request, db: Session = Depends(get_db)):
    user_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not user_id:
        return {"logged_in": False}
    user = db.query(User).filter(User.user_id == int(user_id)).first()
    if not user:
        return {"logged_in": False}
    return {"logged_in": True, "user_id": user.user_id, "username": user.username, "email": user.email}


# -------------------- 루트 기본 접속 테스트 --------------------
@app.get("/")
def read_root():
    return FileResponse("static/upload.html")


# -------------------- 엑셀 업로드 API (중복 예외 처리 반영) --------------------
@app.post("/api/upload")
async def upload_and_parse_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
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
            _save_history(db, current_user.user_id, file.filename, len(contents), "실패")
            raise HTTPException(
                status_code=400,
                detail=f"필수 컬럼이 없습니다: {missing_columns}"
            )

        # 파일 내 행 데이터 시그니처 추출
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

        # 동일한 데이터 시그니처 묶음이 이미 DB에 존재하면 409 예외 처리
        raise_if_duplicate_upload(db, current_user.user_id, upload_signature)

        upload_batch_id = str(uuid4())
        now = datetime.now()
        inventory_items = []

        # 중복 검사를 통과한 데이터만 RawInventory 저장
        for signature, count in upload_signature.items():
            product_name, stock_qty, purchase_price, inbound_date, market_price, sales_qty = signature
            for _ in range(count):
                inventory_items.append(
                    RawInventory(
                        user_id=current_user.user_id,
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
        _save_history(db, current_user.user_id, file.filename, len(contents), "성공")

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
        _save_history(db, current_user.user_id, file.filename, 0, "실패")
        raise HTTPException(
            status_code=500,
            detail=f"엑셀 파싱 중 에러 발생: {str(e)}"
        )


# -------------------- 업로드 기록 조회/삭제 API --------------------
@app.get("/api/history")
def list_history(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = (
        db.query(UploadHistory)
        .filter(UploadHistory.user_id == current_user.user_id)
        .order_by(UploadHistory.upload_date.desc())
        .all()
    )
    return [
        {
            "id": row.id,
            "file_name": row.file_name,
            "size": row.size,
            "status": row.status,
            "upload_date": row.upload_date.isoformat() if row.upload_date else None,
        }
        for row in rows
    ]


@app.delete("/api/history/{history_id}")
def delete_history(
    history_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = (
        db.query(UploadHistory)
        .filter(UploadHistory.id == history_id, UploadHistory.user_id == current_user.user_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="해당 기록을 찾을 수 없습니다.")
    db.delete(row)
    db.commit()
    return {"status": "success"}


@app.delete("/api/history")
def clear_history(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    db.query(UploadHistory).filter(UploadHistory.user_id == current_user.user_id).delete()
    db.commit()
    return {"status": "success"}


# -------------------- 정적 파일 서빙 --------------------
app.mount("/", StaticFiles(directory="static"), name="static")