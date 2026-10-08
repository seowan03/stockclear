import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.llm import LLMFailure, get_upload_diagnosis_summary, run_llm_with_timeout
from app.models import UploadAnalysisSummary, UploadHistory, User
from app.security import get_current_user
from app.services.inventory_service import make_user_summary_input, save_inventory_analysis, save_upload_history
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
UPLOAD_SUMMARY_TIMEOUT_SECONDS = 15


async def _generate_and_save_upload_summary(
    db: Session,
    upload_id: int,
    user_id: int,
) -> str:
    summary_text = None
    summary_data = None
    status = "failed"
    try:
        summary_input = make_user_summary_input(db, user_id)
        summary_scope = summary_input.pop("scope", "account_active_inventory")
        summary_data = json.dumps(
            {"scope": summary_scope, "metrics": summary_input},
            ensure_ascii=False,
        )
        summary_text = await run_llm_with_timeout(
            user_id,
            UPLOAD_SUMMARY_TIMEOUT_SECONDS,
            get_upload_diagnosis_summary,
            {"scope": summary_scope, **summary_input},
        )
        if not isinstance(summary_text, str) or not summary_text.strip():
            raise LLMFailure("empty_response")
        status = "complete"
    except LLMFailure as exc:
        logger.warning(
            "Upload AI summary generation failed",
            extra={
                "upload_id": upload_id,
                "failure_code": exc.failure_code,
                "error_type": type(exc).__name__,
            },
        )
    except Exception as exc:
        logger.warning(
            "Upload AI summary generation failed",
            extra={
                "upload_id": upload_id,
                "failure_code": "internal_error",
                "error_type": type(exc).__name__,
            },
        )

    try:
        summary_row = db.query(UploadAnalysisSummary).filter(
            UploadAnalysisSummary.upload_id == upload_id,
            UploadAnalysisSummary.user_id == user_id,
        ).first()
        if summary_row is None:
            summary_row = UploadAnalysisSummary(
                upload_id=upload_id,
                user_id=user_id,
            )
            db.add(summary_row)
        summary_row.status = status
        summary_row.summary_text = summary_text
        summary_row.summary_data = summary_data
        summary_row.generated_at = datetime.utcnow()
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Upload AI summary persistence failed", extra={"upload_id": upload_id})
        return "failed"
    return status


@router.post("/api/upload/{upload_id}/summary/retry")
async def retry_upload_summary(
    upload_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    upload = db.query(UploadHistory).filter(
        UploadHistory.id == upload_id,
        UploadHistory.user_id == current_user.user_id,
        UploadHistory.status == "성공",
    ).with_for_update().first()
    if upload is None:
        raise HTTPException(status_code=404, detail="업로드 기록을 찾을 수 없습니다.")

    summary_row = db.query(UploadAnalysisSummary).filter(
        UploadAnalysisSummary.upload_id == upload_id,
        UploadAnalysisSummary.user_id == current_user.user_id,
    ).with_for_update().first()
    if summary_row is None or summary_row.status != "failed":
        raise HTTPException(status_code=409, detail="다시 생성할 실패 상태의 AI 종합진단이 없습니다.")

    summary_row.status = "generating"
    db.commit()
    status = await _generate_and_save_upload_summary(db, upload_id, current_user.user_id)
    return {"status": status}


@router.post("/api/upload")
async def upload_and_parse_excel(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filename = file.filename or ""
    if not filename.lower().endswith((".xlsx", ".csv")):
        raise HTTPException(status_code=400, detail="엑셀 파일(.xlsx) 또는 CSV 파일만 업로드 가능합니다.")

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
        # upload_files를 먼저 저장해 id를 확보해야 raw_inventory에 FK로 연결할 수 있다.
        history = save_upload_history(
            db,
            current_user.user_id,
            filename,
            len(contents),
            "성공",
            content_hash,
        )
        save_inventory_analysis(db, current_user.user_id, content_hash, df, upload_file_id=history.id)
        history_id = history.id
        db.commit()
        ai_summary_status = await _generate_and_save_upload_summary(
            db,
            history_id,
            current_user.user_id,
        )
        parsed_data = df.to_dict(orient="records")
        return {
            "status": "success",
            "filename": filename,
            "total_rows": len(parsed_data),
            "data_preview": parsed_data,
            "history_id": history_id,
            "ai_summary_status": ai_summary_status,
        }
    except HTTPException:
        db.rollback()
        raise
    except ValueError as e:
        logger.exception("업로드 데이터 검증 중 오류 발생")
        db.rollback()
        try:
            save_upload_history(db, current_user.user_id, filename, 0, "실패")
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("업로드 실패 이력 저장 중 추가 오류 발생")
        
        error_detail = str(e) if str(e) else "업로드 데이터 형식이 올바르지 않습니다."
        raise HTTPException(status_code=400, detail=error_detail)
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
