import os
import secrets

from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User

load_dotenv()

# -------------------- 세션 관련 --------------------
SESSION_COOKIE_NAME = "session_user"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 7  # 7일

# 쿠키 변조를 막기 위한 서명 키. 운영 환경에서는 반드시 .env에 강력한 값을 설정해야 한다.
SECRET_KEY = os.getenv("SESSION_SECRET_KEY")
if not SECRET_KEY:
    if os.getenv("ENV", "development") == "production":
        raise RuntimeError("SESSION_SECRET_KEY 환경 변수가 설정되지 않았습니다.")
    SECRET_KEY = "dev-only-insecure-secret-key"

session_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="session-cookie")

# HTTPS 배포 환경(ENV=production)에서는 secure 쿠키를 강제한다.
IS_PRODUCTION = os.getenv("ENV", "development") == "production"

# -------------------- OAuth state (CSRF 방지) --------------------
OAUTH_STATE_COOKIE_NAME = "kakao_oauth_state"
OAUTH_STATE_MAX_AGE_SECONDS = 60 * 10  # 10분 (로그인 왕복 시간이면 충분)

oauth_state_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="kakao-oauth-state")


def create_oauth_state() -> str:
    """로그인 CSRF 방지를 위한 예측 불가능한 state 값을 생성한다."""
    return secrets.token_urlsafe(24)


def set_oauth_state_cookie(response: Response, state: str) -> None:
    response.set_cookie(
        OAUTH_STATE_COOKIE_NAME,
        oauth_state_serializer.dumps(state),
        httponly=True,
        samesite="lax",
        secure=IS_PRODUCTION,
        max_age=OAUTH_STATE_MAX_AGE_SECONDS,
    )


def pop_oauth_state_cookie(request: Request) -> str | None:
    """서명 쿠키에 저장된 state 값을 검증한다. 위조/만료/누락 시 None을 반환한다."""
    token = request.cookies.get(OAUTH_STATE_COOKIE_NAME)
    if not token:
        return None
    try:
        return oauth_state_serializer.loads(token, max_age=OAUTH_STATE_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None


def clear_oauth_state_cookie(response: Response) -> None:
    response.delete_cookie(OAUTH_STATE_COOKIE_NAME)


def create_session_token(user_id: int) -> str:
    """user_id를 서명된(변조 불가능한) 토큰으로 인코딩한다."""
    return session_serializer.dumps({"user_id": user_id})


def verify_session_token(token: str) -> int | None:
    """서명을 검증하고 user_id를 복원한다. 위조/만료된 값이면 None을 반환한다."""
    try:
        data = session_serializer.loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except (BadSignature, SignatureExpired):
        return None
    return data.get("user_id")


def set_session_cookie(response: Response, user_id: int) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        create_session_token(user_id),
        httponly=True,
        samesite="lax",
        secure=IS_PRODUCTION,
        max_age=SESSION_MAX_AGE_SECONDS,
    )


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user_id = verify_session_token(token) if token else None
    if user_id is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    user = db.query(User).filter(User.user_id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return user
