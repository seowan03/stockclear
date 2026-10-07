from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CustomerInquiry, User
from app.security import get_current_admin

router = APIRouter(prefix="/api/admin/inquiries", tags=["admin-inquiries"])


class InquiryReplyRequest(BaseModel):
    reply: str = Field(min_length=1, max_length=5000)


@router.get("")
def list_inquiries(
    status: Literal["접수", "답변 완료"] | None = Query(default=None),
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    query = db.query(CustomerInquiry, User.email).outerjoin(
        User,
        CustomerInquiry.user_id == User.user_id,
    )
    if status:
        query = query.filter(CustomerInquiry.status == status)
    rows = query.order_by(CustomerInquiry.created_at.desc(), CustomerInquiry.inquiry_id.desc()).all()
    return {
        "items": [
            {
                "inquiry_id": inquiry.inquiry_id,
                "user_email": email,
                "inquiry_type": inquiry.inquiry_type,
                "subject": inquiry.subject,
                "content": inquiry.content,
                "status": inquiry.status,
                "reply": inquiry.admin_reply,
                "created_at": inquiry.created_at.isoformat() if inquiry.created_at else None,
                "replied_at": inquiry.replied_at.isoformat() if inquiry.replied_at else None,
            }
            for inquiry, email in rows
        ],
        "admin_user_id": current_admin.user_id,
    }


@router.patch("/{inquiry_id}")
def reply_to_inquiry(
    inquiry_id: int,
    data: InquiryReplyRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin),
):
    reply = data.reply.strip()
    if not reply:
        raise HTTPException(status_code=422, detail="답변 내용을 입력해주세요.")
    inquiry = db.query(CustomerInquiry).filter(
        CustomerInquiry.inquiry_id == inquiry_id,
    ).with_for_update().first()
    if inquiry is None:
        raise HTTPException(status_code=404, detail="문의를 찾을 수 없습니다.")

    inquiry.admin_reply = reply
    inquiry.status = "답변 완료"
    inquiry.replied_at = datetime.utcnow()
    inquiry.replied_by_user_id = current_admin.user_id
    db.commit()
    return {
        "status": inquiry.status,
        "inquiry_id": inquiry.inquiry_id,
        "replied_at": inquiry.replied_at.isoformat(),
    }