import hashlib
import hmac
import secrets
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CustomerInquiry, User
from app.security import get_session_user_id

router = APIRouter(prefix="/api/inquiries", tags=["inquiries"])


class InquiryRequest(BaseModel):
    inquiry_type: Literal["이용 안내", "구매 안내", "환불 안내", "기타 문의"]
    subject: str = Field(min_length=1, max_length=50)
    content: str = Field(min_length=1, max_length=5000)


@router.post("")
def create_inquiry(
    data: InquiryRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    subject = data.subject.strip()
    content = data.content.strip()
    if not subject or not content:
        raise HTTPException(status_code=422, detail="문의 제목과 내용을 입력해주세요.")

    user_id = get_session_user_id(request)
    if user_id is not None and not db.query(User.user_id).filter(User.user_id == user_id).first():
        user_id = None

    reply_token = secrets.token_urlsafe(32) if user_id is None else None
    inquiry = CustomerInquiry(
        user_id=user_id,
        inquiry_type=data.inquiry_type,
        subject=subject,
        content=content,
        reply_token_hash=hashlib.sha256(reply_token.encode("utf-8")).hexdigest() if reply_token else None,
    )
    db.add(inquiry)
    db.commit()
    db.refresh(inquiry)
    return {"status": "success", "inquiry_id": inquiry.inquiry_id, "reply_token": reply_token}


@router.get("/{inquiry_id}/reply")
def get_inquiry_reply(
    inquiry_id: int,
    request: Request,
    token: str | None = None,
    db: Session = Depends(get_db),
):
    inquiry = db.query(CustomerInquiry).filter(CustomerInquiry.inquiry_id == inquiry_id).first()
    if inquiry is None:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다.")

    session_user_id = get_session_user_id(request)
    is_owner = inquiry.user_id is not None and session_user_id == inquiry.user_id
    has_valid_reply_token = False
    if token and inquiry.reply_token_hash:
        supplied_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        has_valid_reply_token = hmac.compare_digest(supplied_hash, inquiry.reply_token_hash)
    if not is_owner and not has_valid_reply_token:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다.")

    return {
        "inquiry_id": inquiry.inquiry_id,
        "subject": inquiry.subject,
        "status": inquiry.status,
        "reply": inquiry.admin_reply,
        "created_at": inquiry.created_at.isoformat() if inquiry.created_at else None,
        "replied_at": inquiry.replied_at.isoformat() if inquiry.replied_at else None,
    }