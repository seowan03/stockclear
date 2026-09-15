from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from werkzeug.security import check_password_hash, generate_password_hash

from app.database import SessionLocal
from app.models import User

router = APIRouter()


class SignupRequest(BaseModel):
  username: str
  email: str
  password: str


class LoginRequest(BaseModel):
  email: str
  password: str


def get_user_by_email(email):
  db = SessionLocal()
  try:
    return db.query(User).filter(User.email == email).first()
  finally:
    db.close()


def get_user_by_id(user_id):
  db = SessionLocal()
  try:
    return db.query(User).filter(User.user_id == user_id).first()
  finally:
    db.close()


def insert_user(username, email, password_hash):
  db = SessionLocal()
  try:
    new_user = User(
        username=username,
        email=email,
        password_hash=password_hash,
        created_at=datetime.now(),
    )
    db.add(new_user)
    db.commit()
    print(f"유저 삽입 성공: {username} ({email})")
    return True

  except Exception as e:
    db.rollback()
    print(f"데이터 삽입 중 오류 발생: {e}")
    return False

  finally:
    db.close()


@router.post("/api/signup")
def signup(payload: SignupRequest):
  username = payload.username.strip()
  email = payload.email.strip().lower()
  password = payload.password

  if not username or not email or not password:
    raise HTTPException(status_code=400, detail="아이디, 이메일, 비밀번호를 모두 입력해주세요.")

  # 이메일로 database 조회 후 중복 여부 확인
  if get_user_by_email(email):
    raise HTTPException(status_code=409, detail="이미 가입된 이메일입니다.")

  password_hash = generate_password_hash(password)
  if not insert_user(username=username, email=email, password_hash=password_hash):
    raise HTTPException(status_code=500, detail="회원가입 처리 중 오류가 발생했습니다.")

  return {"status": "success", "message": "회원가입이 완료되었습니다. 로그인해주세요."}


@router.post("/api/login")
def login(payload: LoginRequest, response: Response):
  email = payload.email.strip().lower()
  password = payload.password

  # database에서 사용자 조회 후 비밀번호 일치 여부 확인
  user = get_user_by_email(email)
  if user is None or not check_password_hash(user.password_hash, password):
    raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 일치하지 않습니다.")

  response.set_cookie(
      key="session_user",
      value=str(user.user_id),
      httponly=True,
      samesite="lax",
      max_age=60 * 60 * 24,
  )

  return {"status": "success", "user_id": user.user_id, "username": user.username}


@router.post("/api/logout")
def logout(response: Response):
  response.delete_cookie("session_user")
  return {"status": "success"}


@router.get("/api/me")
def me(request: Request):
  raw_user_id = request.cookies.get("session_user")
  if raw_user_id is None or not raw_user_id.isdigit():
    return {"logged_in": False}

  user = get_user_by_id(int(raw_user_id))
  if user is None:
    return {"logged_in": False}

  return {"logged_in": True, "user_id": user.user_id, "username": user.username}
