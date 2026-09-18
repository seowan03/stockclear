import io
import hashlib
import json
from datetime import datetime
from fastapi import Depends, FastAPI, Request, Response, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from app.database import Base, engine, ensure_upload_files_user_id_column, get_db
from app.models import AnalysisResult, RawInventory, UploadHistory, User
from app.router import raise_if_duplicate_upload

from app.analysis import analyze_inventory

SESSION_COOKIE_NAME = "session_user"
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10MB

# 대시보드/전략 화면에서 사용하는 위험등급별 표시 정보
RISK_GRADE_META = {
    "정상": {"color": "#10b981", "title": "정상 운영 대상", "summary": "현재 재고 운영 상태가 양호합니다."},
    "주의": {"color": "#f59e0b", "title": "모니터링 대상", "summary": "안전재고 수준을 벗어나기 전 지속적인 관찰이 필요합니다."},
    "위험": {"color": "#ef4444", "title": "할인 프로모션 대상", "summary": "결품/체류 위험이 있어 할인 및 프로모션 검토가 필요합니다."},
    "처분 권장": {"color": "#a855f7", "title": "즉시 처분 대상", "summary": "회전율이 낮고 감가가 심해 빠른 재고 소진이 필요합니다."},
}

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

        if len(contents) > MAX_UPLOAD_SIZE_BYTES:
            _save_history(db, current_user.user_id, file.filename, len(contents), "실패")
            raise HTTPException(
                status_code=400,
                detail="파일 용량은 10MB를 초과할 수 없습니다."
            )

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

        content_hash = make_upload_content_hash(df, required_columns)
        raise_if_duplicate_upload(db, current_user.user_id, content_hash)

        df = analyze_inventory(df)

        _save_analysis_results(db, current_user.user_id, content_hash, df)

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
    except ValueError as e:
        _save_history(db, current_user.user_id, file.filename, 0, "실패")
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        _save_history(db, current_user.user_id, file.filename, 0, "실패")
        raise HTTPException(
            status_code=500,
            detail=f"엑셀 파싱 중 에러 발생: {str(e)}"
        )


def _save_analysis_results(db: Session, user_id: int, upload_batch_id: str, df: pd.DataFrame) -> None:
    """분석 결과를 raw_inventory/analysis_results 테이블에 저장해 대시보드/재고 목록 API가 조회할 수 있게 한다."""
    for _, row in df.iterrows():
        raw_item = RawInventory(
            user_id=user_id,
            upload_batch_id=upload_batch_id,
            product_name=row["product_name"],
            stock_qty=int(row["stock_qty"]),
            purchase_price=float(row["purchase_price"]),
            market_price=float(row["selling_price"]),
            inbound_date=row["received_date"].date(),
            created_at=datetime.utcnow(),
        )
        db.add(raw_item)
        db.flush()

        db.add(AnalysisResult(
            item_id=raw_item.item_id,
            sales_velocity=float(row["sales_speed"]),
            aging_days=int(row["storage_days"]),
            days_to_sell=int(min(row["days_to_sell"], 9999)),
            risk_grade=row["risk_grade"],
            inventory_amount=float(row["inventory_value"]),
            final_score=float(row["final_score"]),
            fluctuation_rate=float(row["depreciation_rate"]),
            updated_at=datetime.utcnow(),
        ))

    db.commit()


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


# -------------------- 분석 결과 조회 API (대시보드/재고 목록/전략/내보내기) --------------------
def _query_user_analysis(db: Session, user_id: int):
    return (
        db.query(AnalysisResult, RawInventory)
        .join(RawInventory, AnalysisResult.item_id == RawInventory.item_id)
        .filter(RawInventory.user_id == user_id)
    )


@app.get("/api/dashboard")
def get_dashboard(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = _query_user_analysis(db, current_user.user_id).all()

    if not rows:
        return {
            "total_sku": 0,
            "risk_count": 0,
            "aging_count": 0,
            "monthly_saving": 0,
            "grades": [],
            "risk_items": [],
        }

    grade_counts: dict[str, int] = {}
    risk_count = 0
    aging_count = 0
    monthly_saving = 0.0

    for analysis, _ in rows:
        grade_counts[analysis.risk_grade] = grade_counts.get(analysis.risk_grade, 0) + 1
        if analysis.risk_grade in ("위험", "처분 권장"):
            risk_count += 1
            # 처분 권장/위험 재고를 정리했을 때 회수 가능한 재고금액의 10%를 월 절감액으로 추정
            monthly_saving += float(analysis.inventory_amount or 0) * 0.1
        if analysis.aging_days >= 60:
            aging_count += 1

    risk_items = sorted(
        (
            {"product_name": item.product_name, "final_score": analysis.final_score}
            for analysis, item in rows
        ),
        key=lambda x: x["final_score"],
        reverse=True,
    )[:5]

    return {
        "total_sku": len(rows),
        "risk_count": risk_count,
        "aging_count": aging_count,
        "monthly_saving": round(monthly_saving),
        "grades": [
            {"name": name, "count": count, "color": RISK_GRADE_META.get(name, {}).get("color", "#64748b")}
            for name, count in grade_counts.items()
        ],
        "risk_items": risk_items,
    }


@app.get("/api/inventory")
def list_inventory(
    search: str = "",
    status: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = _query_user_analysis(db, current_user.user_id)
    if search:
        query = query.filter(RawInventory.product_name.contains(search))
    if status:
        query = query.filter(AnalysisResult.risk_grade == status)

    rows = query.order_by(AnalysisResult.final_score.desc()).all()

    return {
        "items": [
            {
                "item_id": item.item_id,
                "product_name": item.product_name,
                "stock_qty": item.stock_qty,
                "aging_days": analysis.aging_days,
                "days_to_sell": analysis.days_to_sell,
                "risk_grade": analysis.risk_grade,
                "action_plans": analysis.action_plans,
            }
            for analysis, item in rows
        ]
    }


@app.get("/api/inventory/{item_id}")
def get_inventory_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = _query_user_analysis(db, current_user.user_id).filter(RawInventory.item_id == item_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="해당 재고를 찾을 수 없습니다.")

    analysis, item = row
    return {
        "item_id": item.item_id,
        "product_name": item.product_name,
        "stock_qty": item.stock_qty,
        "aging_days": analysis.aging_days,
        "days_to_sell": analysis.days_to_sell,
        "risk_grade": analysis.risk_grade,
        "ai_diagnosis": analysis.ai_diagnosis,
    }


@app.get("/api/strategy")
def get_strategy(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = (
        db.query(AnalysisResult.risk_grade, func.count(AnalysisResult.result_id))
        .join(RawInventory, AnalysisResult.item_id == RawInventory.item_id)
        .filter(RawInventory.user_id == current_user.user_id)
        .group_by(AnalysisResult.risk_grade)
        .all()
    )

    groups = [
        {
            "type": grade,
            "title": RISK_GRADE_META.get(grade, {}).get("title", grade),
            "summary": RISK_GRADE_META.get(grade, {}).get("summary", ""),
            "count": count,
        }
        for grade, count in rows
    ]

    return {"groups": groups}


@app.get("/api/export")
def get_export(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = _query_user_analysis(db, current_user.user_id).order_by(AnalysisResult.final_score.desc()).all()

    items = [
        {
            "item_id": item.item_id,
            "product_name": item.product_name,
            "stock_qty": item.stock_qty,
            "aging_days": analysis.aging_days,
            "risk_grade": analysis.risk_grade,
            "action_plans": analysis.action_plans,
        }
        for analysis, item in rows
    ]

    return {
        "summary": f"총 {len(items)}개 품목의 재고 분석 리포트입니다.",
        "items": items,
    }


# -------------------- 정적 HTML/CSS/JavaScript 페이지 연결 --------------------
# 위의 명시적 라우트("/", "/api/...")에 안 걸린 나머지 경로를
# static 폴더에서 파일명 그대로 서빙
app.mount("/js", StaticFiles(directory="js"), name="js")
app.mount("/", StaticFiles(directory="static"), name="static")
