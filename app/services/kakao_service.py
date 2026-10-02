import logging
import os
from datetime import datetime, timezone

import requests
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash

from app.config import KAKAO_CLIENT_ID, KAKAO_CLIENT_SECRET, KAKAO_REDIRECT_URI
from app.models import User

logger = logging.getLogger(__name__)

# 카카오 API 호출 실패 시 사용자에게 그대로 노출하지 않기 위한 공통 예외
class KakaoLoginError(Exception):
    pass


def get_kakao_authorization_url(state: str) -> str:
    return (
        "https://kauth.kakao.com/oauth/authorize"
        f"?client_id={KAKAO_CLIENT_ID}"
        f"&redirect_uri={KAKAO_REDIRECT_URI}"
        "&response_type=code"
        f"&state={state}"
    )


def _request_kakao_json(method: str, url: str, **kwargs) -> dict:
    try:
        response = requests.request(method, url, timeout=10, **kwargs)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        logger.exception("Kakao API request failed: %s %s", method, url)
        raise KakaoLoginError("카카오 로그인 서버와 통신에 실패했습니다.") from exc
    except ValueError as exc:
        logger.exception("Kakao API returned invalid JSON: %s %s", method, url)
        raise KakaoLoginError("카카오 로그인 응답을 처리할 수 없습니다.") from exc


def get_or_create_kakao_user(code: str, db: Session) -> User:
    token_json = _request_kakao_json(
        "POST",
        "https://kauth.kakao.com/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": KAKAO_CLIENT_ID,
            "client_secret": KAKAO_CLIENT_SECRET,
            "redirect_uri": KAKAO_REDIRECT_URI,
            "code": code,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
    )
    access_token = token_json.get("access_token")
    if not access_token:
        # token_json 전체를 로그로 남기면 향후 응답 형식이 바뀔 때 민감정보가 섞여 들어갈 수 있어 특정 키만 남긴다
        logger.warning(
            "Kakao token issuance failed: %s",
            token_json.get("error_description") or token_json.get("error") or "unknown_error",
        )
        raise KakaoLoginError("카카오 로그인에 실패했습니다.")

    user_info = _request_kakao_json(
        "GET",
        "https://kapi.kakao.com/v2/user/me",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
        },
    )
    kakao_account = user_info.get("kakao_account", {})
    email = kakao_account.get("email") or f"kakao_{user_info.get('id')}@stockclear.com"
    nickname = user_info.get("properties", {}).get("nickname", "카카오사용자")

    user = db.query(User).filter(User.email == email).first()
    if user:
        return user

    user = User(
        username=nickname,
        email=email,
        password_hash=generate_password_hash(os.urandom(16).hex()),
        created_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user