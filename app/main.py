import io
import hashlib
import json
import uuid
from datetime import datetime
from fastapi import Depends, FastAPI, Request, Response, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from app.database import Base, engine, ensure_upload_files_user_id_column, get_db
from app.models import AnalysisResult, RawInventory, UploadHistory, User
from app.router import raise_if_duplicate_upload, router
from app.schemas import InventoryItem

from app.analysis import analyze_inventory

SESSION_COOKIE_NAME = "session_user"

app = FastAPI(title="StockClear Backend", version="1.0")


def make_upload_content_hash(df, required_columns):
    """필수 컬럼의 실제 값으로 업로드 내용의 일관된 해시를 생성한다."""
    normalized_data = df[required_columns].copy()
    normalized_data["입고일"] = normalized_data["입고일"].map(
        lambda value: None if pd.isna(value) else pd.to_datetime(value).date().isoformat()
    )
    records = normalized_data.where(pd.notna(normalized_data), None).to_dict(orient="records")
    serialized_data = json.dumps(records, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized_data.encode("utf-8")).hexdigest()


def _risk_grade(storage_days: int, stock_qty: int, sales_speed: float) -> str:
    """프런트엔드의 재고 상태 분류 기준과 같은 등급을 반환한다."""
    if stock_qty <= 0:
        return "처분 권장"
    if storage_days >= 60 or (sales_speed == 0 and storage_days > 30):
        return "장기 체류"
    if storage_days >= 30:
        return "주의"
    return "정상"


def _store_analysis_results(db: Session, user_id: int, dataframe: pd.DataFrame) -> None:
    """업로드 시 계산한 재고 및 분석 결과를 사용자별로 함께 저장한다."""
    upload_batch_id = str(uuid.uuid4())

    for record in dataframe.to_dict(orient="records"):
        raw_inventory = RawInventory(
            user_id=user_id,
            upload_batch_id=upload_batch_id,
            product_name=record["product_name"],
            stock_qty=int(record["stock_qty"]),
            purchase_price=float(record["purchase_price"]),
            market_price=float(record["selling_price"]),
            inbound_date=record["received_date"].date(),
            created_at=datetime.utcnow(),
        )
        db.add(raw_inventory)
        db.flush()

        storage_days = int(record["storage_days"])
        sales_speed = float(record["sales_speed"])
        db.add(AnalysisResult(
            item_id=raw_inventory.item_id,
            sales_velocity=sales_speed,
            aging_days=storage_days,
            days_to_sell=int(round(float(record["days_to_sell"]))),
            risk_grade=_risk_grade(storage_days, raw_inventory.stock_qty, sales_speed),
            inventory_amount=float(record["inventory_value"]),
            fluctuation_rate=float(record["depreciation_rate"]),
            final_score=min(100, round(storage_days / 1.2 + float(record["depreciation_rate"]))),
            updated_at=datetime.utcnow(),
        ))

    db.commit()


def _inventory_items(db: Session, user_id: int) -> list[dict]:
    """로그인 사용자의 재고와 계산 결과를 API 응답 형식으로 결합한다."""
    rows = (
        db.query(RawInventory, AnalysisResult)
        .outerjoin(AnalysisResult, AnalysisResult.item_id == RawInventory.item_id)
        .filter(RawInventory.user_id == user_id)
        .order_by(RawInventory.item_id.desc())
        .all()
    )
    return [
        {
            "item_id": inventory.item_id,
            "product_name": inventory.product_name,
            "stock_qty": inventory.stock_qty,
            "purchase_price": float(inventory.purchase_price or 0),
            "selling_price": float(inventory.market_price or 0),
            "received_date": inventory.inbound_date.isoformat() if inventory.inbound_date else None,
            "aging_days": result.aging_days if result else 0,
            "days_to_sell": result.days_to_sell if result else 0,
            "risk_grade": result.risk_grade if result else "정상",
            "final_score": result.final_score if result else 0,
            "ai_diagnosis": result.ai_diagnosis if result else None,
            "action_plans": result.action_plans if result else None,
        }
        for inventory, result in rows
    ]

# -------------------- 앱 시작 시 테이블 자동 생성 --------------------
@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    ensure_upload_files_user_id_column()

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


# -------------------- 로그인/인증 --------------------
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

# -------------------- 엑셀 업로드 API (임시) --------------------
# response_model=UploadResponse 부분은 schemas 작업 전이므로 임시 제거했습니다.
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

        required_columns = ["상품명", "재고량", "카테고리", "원가", "입고일", "판매가", "판매량"]
        missing_columns = [col for col in required_columns if col not in df.columns]

        if missing_columns:
            _save_history(db, current_user.user_id, file.filename, len(contents), "실패")
            raise HTTPException(
                status_code=400,
                detail=f"필수 컬럼이 없습니다: {missing_columns}"
            )

        content_hash = make_upload_content_hash(df, required_columns)
        raise_if_duplicate_upload(db, current_user.user_id, content_hash)

        df = analyze_inventory(df)
        # 계산값을 DB에 보관해 다른 화면과 브라우저에서도 동일한 분석 결과를 쓴다.
        _store_analysis_results(db, current_user.user_id, df)

        parsed_data = df.to_dict(orient="records")

        _save_history(
            db,
            current_user.user_id,
            file.filename,
            len(contents),
            "성공",
            content_hash,
        )

        return {
            "status": "success",
            "filename": file.filename,
            "total_rows": len(parsed_data),
            "data_preview": parsed_data
        }

    except HTTPException:
        raise
    except Exception as e:
        _save_history(db, current_user.user_id, file.filename, 0, "실패")
        raise HTTPException(
            status_code=500,
            detail=f"엑셀 파싱 중 에러 발생: {str(e)}"
        )


# -------------------- 분석 결과 조회 API --------------------
@app.get("/api/inventory")
def list_inventory(
    search: str = "",
    status: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = _inventory_items(db, current_user.user_id)
    if search:
        normalized_search = search.lower()
        items = [item for item in items if normalized_search in item["product_name"].lower()]
    if status:
        items = [item for item in items if item["risk_grade"] == status]
    return {"items": items}


@app.get("/api/inventory/{item_id}")
def get_inventory_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = next((item for item in _inventory_items(db, current_user.user_id) if item["item_id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="재고 항목을 찾을 수 없습니다.")
    return item


@app.get("/api/dashboard")
def get_dashboard(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    items = _inventory_items(db, current_user.user_id)
    risk_items = [item for item in items if item["risk_grade"] in {"주의", "장기 체류", "처분 권장"}]
    aging_items = [item for item in items if item["aging_days"] >= 60]
    grades = [
        {"name": grade, "count": sum(item["risk_grade"] == grade for item in items), "color": color}
        for grade, color in [("정상", "#10b981"), ("주의", "#f59e0b"), ("장기 체류", "#f97316"), ("처분 권장", "#ef4444")]
    ]
    return {
        "total_sku": len(items),
        "risk_count": len(risk_items),
        "aging_count": len(aging_items),
        "monthly_saving": sum(item["purchase_price"] * item["stock_qty"] for item in risk_items),
        "grades": grades,
        "risk_items": sorted(risk_items, key=lambda item: item["final_score"], reverse=True)[:10],
    }


@app.get("/api/strategy")
def get_strategy(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    items = _inventory_items(db, current_user.user_id)
    groups = []
    for grade, title, summary in [
        ("처분 권장", "즉시 처분", "재고 소진을 위한 할인 또는 묶음 판매가 필요합니다."),
        ("장기 체류", "판매 촉진", "장기 보관 재고의 노출과 할인 전략을 검토하세요."),
        ("주의", "재고 모니터링", "판매 추이를 확인하고 추가 입고를 조절하세요."),
    ]:
        count = sum(item["risk_grade"] == grade for item in items)
        if count:
            groups.append({"type": grade, "title": title, "summary": summary, "count": count})
    return {"groups": groups}


@app.get("/api/export")
def get_export(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    items = _inventory_items(db, current_user.user_id)
    risk_count = sum(item["risk_grade"] != "정상" for item in items)
    return {"summary": f"총 {len(items)}개 재고 중 {risk_count}개 항목을 관리 대상으로 분류했습니다.", "items": items}


# -------------------- AI 처방전 진단 API --------------------
@app.post("/api/ai-diagnose")
async def diagnose_inventory(item: InventoryItem):
    """선택한 재고 항목의 계산값을 AI 처방전 생성기에 전달한다."""
    from app.llm import get_ai_strategy

    ai_result = get_ai_strategy(item.model_dump())
    return {
        "status": "success",
        "product_name": item.product_name,
        "stock_status": ai_result.get("status"),
        "judgment": ai_result.get("comment"),
    }


def _save_history(
    db: Session,
    user_id: int,
    filename: str,
    file_size: int,
    status: str,
    content_hash: str | None = None,
) -> None:
    db.add(UploadHistory(
        user_id=user_id,
        file_name=filename,
        size=file_size,
        status=status,
        content_hash=content_hash,
    ))
    db.commit()


# -------------------- 업로드 기록 조회/삭제 API (로그인한 사용자 본인 기록만) --------------------
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
