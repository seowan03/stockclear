import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import get_current_user
from app.services.inventory_service import save_inventory_analysis, save_upload_history
from app.services.upload_service import (
    make_upload_content_hash,
    parse_and_analyze_upload,
    raise_if_duplicate_upload,
)
from app.utils.file_validation import (
    check_upload_content_length,
    read_upload_file_with_limit,
    validate_upload_file_signature,
)
router = APIRouter(tags=["upload"])
logger = logging.getLogger(__name__)


@router.post("/api/upload")
async def upload_and_parse_excel(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filename = file.filename or ""
    if not filename.lower().endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(status_code=400, detail="엑셀 파일(.xlsx, .xls) 또는 CSV 파일만 업로드 가능합니다.")

    try:
        check_upload_content_length(request)
        contents = await read_upload_file_with_limit(file)
        csv_encoding = validate_upload_file_signature(filename, contents)
        df = parse_and_analyze_upload(contents, filename, csv_encoding)

        content_hash = make_upload_content_hash(df.rename(columns={
            "product_name": "상품명",
            "stock_qty": "재고량",
            "purchase_price": "원가",
            "received_date": "입고일",
            "selling_price": "판매가",
            "sales_qty": "판매량",
        }))
        # 같은 사용자의 동일 내용 성공 업로드는 저장 전에 차단한다.
        raise_if_duplicate_upload(db, current_user.user_id, content_hash)

        # 원본 재고, 분석 결과, 업로드 이력은 하나의 트랜잭션으로 함께 확정한다.
        save_inventory_analysis(db, current_user.user_id, content_hash, df)
        history = save_upload_history(
            db,
            current_user.user_id,
            filename,
            len(contents),
            "성공",
            content_hash,
        )
        history_id = history.id
        db.commit()
        parsed_data = df.to_dict(orient="records")
        return {
            "status": "success",
            "filename": filename,
            "total_rows": len(parsed_data),
            "data_preview": parsed_data,
            "history_id": history_id,
        }
    except HTTPException:
        db.rollback()
        raise
    except ValueError:
        logger.exception("업로드 데이터 검증 중 오류 발생")
        db.rollback()
        try:
            # 실패 이력은 본 처리 rollback 이후 별도 트랜잭션으로 남긴다.
            save_upload_history(db, current_user.user_id, filename, 0, "실패")
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("업로드 실패 이력 저장 중 추가 오류 발생")
        raise HTTPException(status_code=400, detail="업로드 데이터 형식이 올바르지 않습니다. 입력 파일을 확인해주세요.")
    except Exception:
        logger.exception("업로드 처리 중 오류 발생")
        db.rollback()
        try:
            # 실패 이력은 본 처리 rollback 이후 별도 트랜잭션으로 남긴다.
            save_upload_history(db, current_user.user_id, filename, 0, "실패")
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("업로드 실패 이력 저장 중 추가 오류 발생")
        raise HTTPException(status_code=500, detail="업로드 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")
