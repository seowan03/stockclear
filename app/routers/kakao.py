import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import (
    clear_oauth_state_cookie,
    create_oauth_state,
    pop_oauth_state_cookie,
    set_oauth_state_cookie,
    set_session_cookie,
)
from app.services.kakao_service import (
    KakaoLoginError,
    get_kakao_authorization_url,
    get_or_create_kakao_user,
)

router = APIRouter(prefix="/api/auth/kakao", tags=["kakao"])
logger = logging.getLogger(__name__)


@router.get("")
def kakao_login():
    state = create_oauth_state()
    redirect_response = RedirectResponse(get_kakao_authorization_url(state))
    set_oauth_state_cookie(redirect_response, state)
    return redirect_response


@router.get("/callback")
def kakao_callback(code: str, state: str, request: Request, db: Session = Depends(get_db)):
    expected_state = pop_oauth_state_cookie(request)
    if not expected_state or not secrets.compare_digest(expected_state, state):
        raise HTTPException(status_code=400, detail="유효하지 않은 로그인 요청입니다.")

    try:
        user = get_or_create_kakao_user(code, db)
    except KakaoLoginError as exc:
        logger.exception("Kakao login failed")
        raise HTTPException(
            status_code=400,
            detail="카카오 로그인 처리에 실패했습니다.",
        ) from exc

    redirect_response = RedirectResponse(url="/dashboard.html")
    set_session_cookie(redirect_response, user.user_id)
    clear_oauth_state_cookie(redirect_response)
    return redirect_response