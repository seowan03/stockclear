import os
from datetime import datetime, timezone

import requests
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash

from app.config import KAKAO_CLIENT_ID, KAKAO_CLIENT_SECRET, KAKAO_REDIRECT_URI
from app.models import User


def get_kakao_authorization_url() -> str:
    return ("https://kauth.kakao.com/oauth/authorize" f"?client_id={KAKAO_CLIENT_ID}" f"&redirect_uri={KAKAO_REDIRECT_URI}" "&response_type=code")


def get_or_create_kakao_user(code: str, db: Session) -> User:
    token_response = requests.post(
        "https://kauth.kakao.com/oauth/token",
        data={"grant_type": "authorization_code", "client_id": KAKAO_CLIENT_ID, "client_secret": KAKAO_CLIENT_SECRET, "redirect_uri": KAKAO_REDIRECT_URI, "code": code},
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        timeout=10,
    )
    token_json = token_response.json()
    access_token = token_json.get("access_token")
    if not access_token:
        raise ValueError(f"카카오 토큰 발급 실패: {token_json.get('error_description', token_json)}")
    user_info = requests.get(
        "https://kapi.kakao.com/v2/user/me",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        timeout=10,
    ).json()
    account = user_info.get("kakao_account", {})
    email = account.get("email") or f"kakao_{user_info.get('id')}@stockclear.com"
    nickname = user_info.get("properties", {}).get("nickname", "카카오사용자")
    user = db.query(User).filter(User.email == email).first()
    if user:
        return user
    user = User(username=nickname, email=email, password_hash=generate_password_hash(os.urandom(16).hex()), created_at=datetime.now(timezone.utc))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
