import json
import logging
import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.database import get_db
from app.llm import LLMFailure, get_upload_diagnosis_summary, run_llm_with_timeout
from app.models import UploadAnalysisSummary, UploadHistory, User
from app.security import get_current_user
from app.services.inventory_service import (
    lock_user_for_inventory_write,
    make_user_summary_input,
    save_inventory_analysis,
    save_upload_history,
)
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
UPLOAD_DB_MAX_ATTEMPTS = 4
UPLOAD_DB_RETRY_DELAY_SECONDS = 0.25


def _summary_failure_message(failure_code: str) -> str:
    messages = {
        "user_concurrency_limit": "같은 계정의 AI 요청이 진행 중입니다. 완료될 때까지 기다린 뒤 다시 시도해 주세요.",
        "global_concurrency_limit": "AI 요청이 몰려 요약을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.",
        "timeout": "AI 응답 시간이 초과됐습니다. 업로드는 완료됐으니 잠시 후 다시 생성해 주세요.",
        "configuration_error": "AI 요약 설정에 문제가 있습니다. 관리자에게 문의해 주세요.",
        "api_error": "AI 요약 서비스 응답에 문제가 있습니다. 잠시 후 다시 시도해 주세요. 반복되면 관리자에게 문의해 주세요.",
        "schema_validation_error": "AI 요약 문장을 확인하지 못했습니다. 업로드는 완료됐으니 잠시 후 다시 생성해 주세요. 반복되면 관리자에게 문의해 주세요.",
        "evidence_validation_error": "AI 요약의 근거를 확인하지 못했습니다. 업로드는 완료됐으니 잠시 후 다시 생성해 주세요. 반복되면 관리자에게 문의해 주세요.",
    }
    return messages.get(
        failure_code,
        "AI 요약을 만들지 못했습니다. 업로드와 재고 분석은 완료됐으니 잠시 후 다시 시도해 주세요.",
    )


def _is_mysql_deadlock(error: OperationalError) -> bool:
    original_error = getattr(error, "orig", None)
    error_args = getattr(original_error, "args", ())
    if not error_args:
        return False
    try:
        return int(error_args[0]) == 1213
    except (TypeError, ValueError):
        return False


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
        summary_text = _summary_failure_message(exc.failure_code)
        logger.warning(
            "Upload AI summary generation failed (failure_code=%s)",
            exc.failure_code,
            extra={
                "upload_id": upload_id,
                "failure_code": exc.failure_code,
                "error_type": type(exc).__name__,
            },
        )
    except Exception as exc:
        summary_text = _summary_failure_message("internal_error")
        logger.warning(
            "Upload AI summary generation failed (failure_code=internal_error, error_type=%s)",
            type(exc).__name__,
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
    if summary_row is not None and summary_row.status != "failed":
        summary_is_empty_complete = (
            summary_row.status == "complete"
            and not (summary_row.summary_text or "").strip()
        )
        if not summary_is_empty_complete:
            raise HTTPException(status_code=409, detail="다시 생성할 실패 상태의 AI 종합진단이 없습니다.")

    if summary_row is None:
        summary_row = UploadAnalysisSummary(
            upload_id=upload_id,
            user_id=current_user.user_id,
        )
        db.add(summary_row)

    summary_row.status = "generating"
    db.commit()
    status = await _generate_and_save_upload_summary(db, upload_id, current_user.user_id)
    message = None
    if status == "failed":
        message = db.query(UploadAnalysisSummary.summary_text).filter(
            UploadAnalysisSummary.upload_id == upload_id,
            UploadAnalysisSummary.user_id == current_user.user_id,
        ).scalar()
    return {"status": status, "message": message}


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
        for attempt in range(1, UPLOAD_DB_MAX_ATTEMPTS + 1):
            try:
                lock_user_for_inventory_write(db, current_user.user_id)
                # 같은 사용자의 동일 내용 성공 업로드는 저장 전에 차단한다.
                raise_if_duplicate_upload(db, current_user.user_id, content_hash)

                # 업로드 이력, 재고, 분석, 일별 지표를 하나의 트랜잭션으로 확정한다.
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
                break
            except OperationalError as exc:
                db.rollback()
                if not _is_mysql_deadlock(exc) or attempt == UPLOAD_DB_MAX_ATTEMPTS:
                    raise
                logger.warning(
                    "Upload transaction deadlocked; retrying",
                    extra={
                        "user_id": current_user.user_id,
                        "attempt": attempt,
                        "max_attempts": UPLOAD_DB_MAX_ATTEMPTS,
                    },
                )
                await asyncio.sleep(UPLOAD_DB_RETRY_DELAY_SECONDS * attempt)

        ai_summary_status = await _generate_and_save_upload_summary(
            db,
            history_id,
            current_user.user_id,
        )
        ai_summary_message = None
        if ai_summary_status == "failed":
            ai_summary_message = db.query(UploadAnalysisSummary.summary_text).filter(
                UploadAnalysisSummary.upload_id == history_id,
                UploadAnalysisSummary.user_id == current_user.user_id,
            ).scalar()
        parsed_data = df.to_dict(orient="records")
        return {
            "status": "success",
            "filename": filename,
            "total_rows": len(parsed_data),
            "data_preview": parsed_data,
            "history_id": history_id,
            "ai_summary_status": ai_summary_status,
            "ai_summary_message": ai_summary_message,
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
