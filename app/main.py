import io
<<<<<<< HEAD
from fastapi import FastAPI, UploadFile, File, HTTPException
=======
from datetime import datetime
from fastapi import Depends, FastAPI, Request, Response, UploadFile, File, HTTPException
>>>>>>> e7955dc6700508d73dd275ac2a15d57d3f144e07
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
<<<<<<< HEAD

# ---------------------------------------------------------
# 아직 작업 안 한 외부 모듈 임포트는 주석 처리 해둡니다.
# ---------------------------------------------------------
# from analysis import analyze_inventory
# from schemas import UploadResponse
# from router import router


app = FastAPI(title="StockClear Backend", version="1.0")

=======
from pydantic import BaseModel
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from app.database import Base, engine, ensure_upload_files_user_id_column, get_db
from app.models import UploadHistory, User

from app.analysis import analyze_inventory

SESSION_COOKIE_NAME = "session_user"

app = FastAPI(title="StockClear Backend", version="1.0")

# -------------------- 앱 시작 시 테이블 자동 생성 --------------------
@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    ensure_upload_files_user_id_column()

>>>>>>> e7955dc6700508d73dd275ac2a15d57d3f144e07
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

<<<<<<< HEAD
=======

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


>>>>>>> e7955dc6700508d73dd275ac2a15d57d3f144e07
# -------------------- 루트 기본 접속 테스트 --------------------
@app.get("/")
def read_root():
    return FileResponse("static/upload.html")

# -------------------- 엑셀 업로드 API (임시) --------------------
# response_model=UploadResponse 부분은 schemas 작업 전이므로 임시 제거했습니다.
@app.post("/api/upload")
<<<<<<< HEAD
async def upload_and_parse_excel(file: UploadFile = File(...)):
=======
async def upload_and_parse_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
>>>>>>> e7955dc6700508d73dd275ac2a15d57d3f144e07

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
<<<<<<< HEAD
=======
            _save_history(db, current_user.user_id, file.filename, len(contents), "실패")
>>>>>>> e7955dc6700508d73dd275ac2a15d57d3f144e07
            raise HTTPException(
                status_code=400,
                detail=f"필수 컬럼이 없습니다: {missing_columns}"
            )

<<<<<<< HEAD
        # analysis 작업 전이므로 분석 함수(analyze_inventory) 호출 부분은 주석 처리합니다.
        # df = analyze_inventory(df)

        parsed_data = df.to_dict(orient="records")

=======
        df = analyze_inventory(df)

        parsed_data = df.to_dict(orient="records")

        _save_history(db, current_user.user_id, file.filename, len(contents), "성공")

>>>>>>> e7955dc6700508d73dd275ac2a15d57d3f144e07
        return {
            "status": "success",
            "filename": file.filename,
            "total_rows": len(parsed_data),
            "data_preview": parsed_data
        }

    except HTTPException:
        raise
    except Exception as e:
<<<<<<< HEAD
=======
        _save_history(db, current_user.user_id, file.filename, 0, "실패")
>>>>>>> e7955dc6700508d73dd275ac2a15d57d3f144e07
        raise HTTPException(
            status_code=500,
            detail=f"엑셀 파싱 중 에러 발생: {str(e)}"
        )

<<<<<<< HEAD
# 아직 router.py가 없으므로 주석 처리 해둡니다.
# app.include_router(router)
=======

def _save_history(db: Session, user_id: int, filename: str, file_size: int, status: str) -> None:
    db.add(UploadHistory(user_id=user_id, file_name=filename, size=file_size, status=status))
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

# -------------------- 정적 HTML/CSS/JavaScript 페이지 연결 --------------------
# 위의 명시적 라우트("/", "/api/...")에 안 걸린 나머지 경로를
# static 폴더에서 파일명 그대로 서빙
app.mount("/js", StaticFiles(directory="js"), name="js")
app.mount("/", StaticFiles(directory="static"), name="static")
>>>>>>> e7955dc6700508d73dd275ac2a15d57d3f144e07
