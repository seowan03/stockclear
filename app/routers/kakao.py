from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import set_session_cookie
from app.services.kakao_service import get_kakao_authorization_url, get_or_create_kakao_user

router = APIRouter(prefix="/api/auth/kakao", tags=["kakao"])


@router.get("")
def kakao_login():
    return RedirectResponse(get_kakao_authorization_url())


@router.get("/callback")
def kakao_callback(code: str, response: Response, db: Session = Depends(get_db)):
    try:
        user = get_or_create_kakao_user(code, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    redirect_response = RedirectResponse(url="/dashboard.html")
    set_session_cookie(redirect_response, user.user_id)
    return redirect_response
