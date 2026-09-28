from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AnalysisResult, RawInventory, UploadHistory, User
from app.security import get_current_user

router = APIRouter(prefix="/api/history", tags=["history"])


def _delete_uploads_with_inventory(db: Session, user_id: int, uploads: list[UploadHistory]) -> int:
    upload_ids = [upload.id for upload in uploads]
    content_hashes = [upload.content_hash for upload in uploads if upload.content_hash]
    if not upload_ids:
        return 0

    inventory_query = db.query(RawInventory.item_id).filter(RawInventory.user_id == user_id)
    conditions = [RawInventory.upload_file_id.in_(upload_ids)]
    if content_hashes:
        conditions.append(and_(
            RawInventory.upload_file_id.is_(None),
            RawInventory.upload_batch_id.in_(content_hashes),
        ))
    item_ids = [row.item_id for row in inventory_query.filter(or_(*conditions)).all()]
    if item_ids:
        db.query(AnalysisResult).filter(AnalysisResult.item_id.in_(item_ids)).delete(synchronize_session=False)
        db.query(RawInventory).filter(RawInventory.item_id.in_(item_ids)).delete(synchronize_session=False)
    db.query(UploadHistory).filter(
        UploadHistory.user_id == user_id,
        UploadHistory.id.in_(upload_ids),
    ).delete(synchronize_session=False)
    return len(item_ids)


@router.get("")
def list_history(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = db.query(UploadHistory).filter(UploadHistory.user_id == current_user.user_id).order_by(UploadHistory.upload_date.desc()).all()
    return [{"id": row.id, "file_name": row.file_name, "size": row.size, "status": row.status, "upload_date": row.upload_date.isoformat() if row.upload_date else None} for row in rows]


@router.delete("/{history_id}")
def delete_history(history_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    row = db.query(UploadHistory).filter(UploadHistory.id == history_id, UploadHistory.user_id == current_user.user_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="해당 기록을 찾을 수 없습니다.")
    _delete_uploads_with_inventory(db, current_user.user_id, [row])
    db.commit()
    return {"status": "success"}


@router.delete("")
def clear_history(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    uploads = db.query(UploadHistory).filter(UploadHistory.user_id == current_user.user_id).all()
    _delete_uploads_with_inventory(db, current_user.user_id, uploads)
    db.commit()
    return {"status": "success"}
