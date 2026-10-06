from datetime import datetime
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from app.database import get_db
from app.models import User
from app.security import SESSION_COOKIE_NAME, set_session_cookie, verify_session_token

router = APIRouter(prefix="/api/auth", tags=["auth"])

PASSWORD_MIN_LENGTH = 8
PASSWORD_SPECIAL_CHAR_PATTERN = re.compile(r"[^A-Za-z0-9]")


def _validate_password_strength(password: str) -> str:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(f"비밀번호는 {PASSWORD_MIN_LENGTH}자 이상이어야 합니다.")
    if not PASSWORD_SPECIAL_CHAR_PATTERN.search(password):
        raise ValueError("비밀번호에 특수문자를 1자 이상 포함해야 합니다.")
    return password


class SignupRequest(BaseModel):
    username: str
    email: str
    password: str

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return _validate_password_strength(value)


class LoginRequest(BaseModel):
    email: str
    password: str


class ResetPasswordRequest(BaseModel):
    username: str
    email: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return _validate_password_strength(value)


@router.post("/signup")
def signup(data: SignupRequest, response: Response, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="이미 가입된 이메일입니다.")
    user = User(username=data.username, email=data.email, password_hash=generate_password_hash(data.password), created_at=datetime.utcnow())
    db.add(user)
    db.commit()
    db.refresh(user)
    set_session_cookie(response, user.user_id)
    return {"status": "success", "user_id": user.user_id, "username": user.username}


@router.post("/login")
def login(data: LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not user.password_hash or not check_password_hash(user.password_hash, data.password):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")
    set_session_cookie(response, user.user_id)
    return {"status": "success", "user_id": user.user_id, "username": user.username}


@router.post("/reset-password")
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or user.username != data.username:
        raise HTTPException(status_code=400, detail="이메일 또는 이름이 일치하지 않습니다.")
    user.password_hash = generate_password_hash(data.new_password)
    db.commit()
    return {"status": "success"}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"status": "success"}


@router.get("/me")
def me(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user_id = verify_session_token(token) if token else None
    if user_id is None:
        return {"logged_in": False}
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        return {"logged_in": False}
    return {"logged_in": True, "user_id": user.user_id, "username": user.username, "email": user.email}
