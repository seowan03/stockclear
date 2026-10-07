from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CustomerInquiry, User
from app.security import SESSION_COOKIE_NAME, verify_session_token

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

    token = request.cookies.get(SESSION_COOKIE_NAME)
    user_id = verify_session_token(token) if token else None
    if user_id is not None and not db.query(User.user_id).filter(User.user_id == user_id).first():
        user_id = None

    inquiry = CustomerInquiry(
        user_id=user_id,
        inquiry_type=data.inquiry_type,
        subject=subject,
        content=content,
    )
    db.add(inquiry)
    db.commit()
    db.refresh(inquiry)
    return {"status": "success", "inquiry_id": inquiry.inquiry_id}