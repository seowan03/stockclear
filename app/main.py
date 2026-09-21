import io
import hashlib
import json
import uuid
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, Request, Response, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash
from app.database import Base, engine, ensure_upload_files_user_id_column, get_db
from app.models import AnalysisResult, RawInventory, UploadHistory, User
from app.router import raise_if_duplicate_upload, router
from app.analysis import analyze_inventory
from app.security import (
    SESSION_COOKIE_NAME,
    get_current_user,
    set_session_cookie,
    verify_session_token,
)
# -------------------- 카카오 소셜 로그인 관련 --------------------
import os
from dotenv import load_dotenv
import requests # 파일 상단에 requests 임포트가 필요합니다.
load_dotenv()

# -------------------- 세션 관련 --------------------
SESSION_COOKIE_NAME = "session_user"

# 쿠키 서명에 쓰이는 비밀 키. 반드시 .env의 SESSION_SECRET_KEY로 관리하고 외부에 노출하지 않는다.
SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY")
if not SESSION_SECRET_KEY:
    print("⚠️ SESSION_SECRET_KEY가 설정되지 않아 임시 키를 사용합니다. 서버 재시작 시 기존 세션이 모두 무효화됩니다.")
    SESSION_SECRET_KEY = os.urandom(32).hex()

app = FastAPI(title="StockClear Backend", version="1.0")
# router.py의 모든 엔드포인트(/api/ai-diagnose 등)에 로그인 검증을 일괄 적용한다.
app.include_router(router, dependencies=[Depends(get_current_user)])

# -------------------- 카카오 소셜 로그인 --------------------

KAKAO_CLIENT_ID = os.getenv("KAKAO_CLIENT_ID")
KAKAO_CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET")
KAKAO_REDIRECT_URI = os.getenv("KAKAO_REDIRECT_URI", "http://127.0.0.1:8000/api/auth/kakao/callback")

# ----------------------------------------------------
# 1. 카카오 로그인 페이지로 리다이렉트하는 엔드포인트
# ----------------------------------------------------
@app.get("/api/auth/kakao")
def kakao_login():
  kakao_auth_url = (
      f"https://kauth.kakao.com/oauth/authorize"
      f"?client_id={KAKAO_CLIENT_ID}"
      f"&redirect_uri={KAKAO_REDIRECT_URI}"
      f"&response_type=code"
  )
  return RedirectResponse(kakao_auth_url)


# ----------------------------------------------------
# 2. 카카오 로그인 완료 후 돌아오는 콜백 엔드포인트
# ----------------------------------------------------
@app.get("/api/auth/kakao/callback")
def kakao_callback(code: str, response: Response, db: Session = Depends(get_db)):
  # 1. 인가 코드로 액세스 토큰 요청
  token_url = "https://kauth.kakao.com/oauth/token"
  data = {
      "grant_type": "authorization_code",
      "client_id": KAKAO_CLIENT_ID,
      "client_secret": KAKAO_CLIENT_SECRET,
      "redirect_uri": KAKAO_REDIRECT_URI,
      "code": code,
  }
  headers = {"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"}
  token_response = requests.post(token_url, data=data, headers=headers)
  token_json = token_response.json()

  # 터미널에 카카오의 응답을 출력 (디버깅용)
  print("🔥 카카오 응답 데이터:", token_json)

  # 토큰 발급 실패 시 에러 처리 (중복 제거 완료)
  if "access_token" not in token_json:
    error_msg = token_json.get("error_description", str(token_json))
    raise HTTPException(
        status_code=400, detail=f"카카오 토큰 발급 실패: {error_msg}"
    )

  access_token = token_json["access_token"]

  # 2. 액세스 토큰으로 카카오 사용자 정보 조회
  user_info_response = requests.get(
      "https://kapi.kakao.com/v2/user/me",
      headers={
          "Authorization": f"Bearer {access_token}",
          "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
      },
  )
  user_info = user_info_response.json()

  kakao_account = user_info.get("kakao_account", {})
  email = kakao_account.get("email")
  nickname = user_info.get("properties", {}).get("nickname", "카카오사용자")

  # 카카오 계정에 이메일 정보가 동의 항목에 없을 경우의 대체 처리
  if not email:
    email = f"kakao_{user_info.get('id')}@stockclear.com"

  # 3. DB에 이미 가입된 유저인지 확인
  user = db.query(User).filter(User.email == email).first()

  if not user:
    # 가입되어 있지 않다면 자동으로 회원가입 처리 (DB의 password_hash가 NOT NULL이라 사용 불가능한 임의 값을 채움)
    user = User(
        username=nickname,
        email=email,
        password_hash=generate_password_hash(os.urandom(16).hex()),
        created_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

  # 4. 기존 일반 로그인과 동일하게 서명된 세션에 유저 정보 저장
  request.session["user_id"] = user.user_id

  # 5. 로그인이 완료되면 대시보드 페이지로 리다이렉트
  return redirect_response

# -------------------- 앱 시작 시 테이블 자동 생성 --------------------

def make_upload_content_hash(df, required_columns):
    """필수 컬럼의 실제 값으로 업로드 내용의 일관된 해시를 생성한다."""
    normalized_data = df[required_columns].copy()
    normalized_data["입고일"] = normalized_data["입고일"].map(
        lambda value: None if pd.isna(value) else pd.to_datetime(value).date().isoformat()
    )
    records = normalized_data.where(pd.notna(normalized_data), None).to_dict(orient="records")
    serialized_data = json.dumps(records, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(serialized_data.encode("utf-8")).hexdigest()

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
    user_id = request.session.get("user_id")
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

    request.session["user_id"] = user.user_id
    return {"status": "success", "user_id": user.user_id, "username": user.username}


@app.post("/api/auth/login")
def login(data: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not user.password_hash or not check_password_hash(user.password_hash, data.password):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")

    request.session["user_id"] = user.user_id
    return {"status": "success", "user_id": user.user_id, "username": user.username}


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"status": "success"}


@app.get("/api/auth/me")
def me(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return {"logged_in": False}
    user = db.query(User).filter(User.user_id == user_id).first()
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

        parsed_data = df.to_dict(orient="records")

        history = _save_history(
            db,
            current_user.user_id,
            file.filename,
            len(contents),
            "성공",
            content_hash,
        )
        _save_raw_inventory(db, current_user.user_id, history.id, df)

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


def _save_history(
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
    db.commit()
    db.refresh(history)
    return history


def _save_raw_inventory(db: Session, user_id: int, batch_id: int, df: pd.DataFrame) -> None:
    """업로드된 엑셀 행들을 raw_inventory 테이블에 저장한다."""
    # analyze_inventory()가 컬럼명을 영문으로 변환한 뒤의 df를 받는다.
    now = datetime.utcnow()
    rows = [
        RawInventory(
            user_id=user_id,
            upload_batch_id=str(batch_id),
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
    db.add_all(rows)
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