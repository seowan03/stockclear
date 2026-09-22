from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import UploadHistory, User
from app.security import get_current_user

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("")
def list_history(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = (
        db.query(UploadHistory)
        .filter(UploadHistory.user_id == current_user.user_id)
        .order_by(UploadHistory.upload_date.desc())
        .all()
    )
    return [
        {
            "id": row.id,
            "file_name": row.file_name,
            "size": row.size,
            "status": row.status,
            "upload_date": row.upload_date.isoformat() if row.upload_date else None,
        }
        for row in rows
    ]


@router.delete("/{history_id}")
def delete_history(history_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = (
        db.query(UploadHistory)
        .filter(UploadHistory.id == history_id, UploadHistory.user_id == current_user.user_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="해당 기록을 찾을 수 없습니다.")
    db.delete(row)
    db.commit()
    return {"status": "success"}


@router.delete("")
def clear_history(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    db.query(UploadHistory).filter(UploadHistory.user_id == current_user.user_id).delete()
    db.commit()
    return {"status": "success"}
