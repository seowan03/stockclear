from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import CORS_ORIGINS
from app.database import Base, engine, ensure_upload_files_user_id_column
from app.routers import ai, auth, history, inventory, kakao, upload

app = FastAPI(title="StockClear Backend", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(kakao.router)
app.include_router(upload.router)
app.include_router(history.router)
app.include_router(inventory.router)
app.include_router(ai.router)



def _check_upload_content_length(request: Request) -> None:
    content_length = request.headers.get("content-length")
    if not content_length:
        return
    try:
        request_size = int(content_length)
    except ValueError:
        raise HTTPException(status_code=400, detail="업로드 요청 크기 정보가 올바르지 않습니다.")
    if request_size > MAX_UPLOAD_BODY_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail="업로드 요청 크기가 허용 범위를 초과했습니다.",
        )


async def _read_upload_file_with_limit(file: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total_size = 0

    while True:
        chunk = await file.read(UPLOAD_READ_CHUNK_SIZE)
        if not chunk:
            break

        total_size += len(chunk)
        if total_size > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(
                status_code=413,
                detail="파일 용량은 10MB를 초과할 수 없습니다.",
            )
        chunks.append(chunk)

    if total_size == 0:
        raise HTTPException(status_code=400, detail="빈 파일은 업로드할 수 없습니다.")

    return b"".join(chunks)


def _detect_csv_encoding(contents: bytes) -> str:
    for encoding in ("utf-8-sig", "cp949"):
        try:
            contents.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    raise HTTPException(status_code=400, detail="파일 내용이 CSV 형식이 아닙니다.")


def _validate_upload_file_signature(filename: str, contents: bytes) -> str | None:
    normalized_filename = filename.lower()
    if normalized_filename.endswith(".xlsx"):
        if not contents.startswith(b"PK"):
            raise HTTPException(status_code=400, detail="파일 내용이 XLSX 형식이 아닙니다.")
        return None
    if normalized_filename.endswith(".xls"):
        if not contents.startswith(b"\xd0\xcf\x11\xe0"):
            raise HTTPException(status_code=400, detail="파일 내용이 XLS 형식이 아닙니다.")
        return None
    return _detect_csv_encoding(contents)

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    ensure_upload_files_user_id_column()


@app.get("/")
def read_root():
    return FileResponse("static/upload.html")

# -------------------- 엑셀 업로드 API (임시) --------------------
# response_model=UploadResponse 부분은 schemas 작업 전이므로 임시 제거했습니다.
@app.post("/api/upload")
async def upload_and_parse_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):

    if not file.filename.endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(
            status_code=400,
            detail="엑셀 파일(.xlsx, .xls) 또는 CSV 파일만 업로드 가능합니다."
        )

    try:
        contents = await file.read()

        if len(contents) == 0:
            _save_history(db, current_user.user_id, file.filename, 0, "실패")
            raise HTTPException(status_code=400, detail="빈 파일은 업로드할 수 없습니다.")

        if len(contents) > MAX_UPLOAD_SIZE_BYTES:
            _save_history(db, current_user.user_id, file.filename, len(contents), "실패")
            raise HTTPException(
                status_code=400,
                detail="파일 용량은 10MB를 초과할 수 없습니다."
            )

        if file.filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(contents))
        else:
            df = pd.read_csv(io.BytesIO(contents))

        # 최대 5만 행으로 처리 범위 제한
        MAX_ROWS = 50_000
        if len(df) > MAX_ROWS:
            raise HTTPException(status_code=400, detail=f"행 수는 {MAX_ROWS}개를 초과할 수 없습니다.")

        required_columns = ["상품명", "재고량", "원가", "입고일", "판매가", "판매량"]
        missing_columns = [col for col in required_columns if col not in df.columns]

        if missing_columns:
            _save_history(db, current_user.user_id, file.filename, len(contents), "실패")
            raise HTTPException(
                status_code=400,
                detail=f"필수 컬럼이 없습니다: {missing_columns}"
            )

        content_hash = make_upload_content_hash(df, required_columns)
        raise_if_duplicate_upload(db, current_user.user_id, content_hash)

        df = analyze_inventory(df)

        _save_analysis_results(db, current_user.user_id, content_hash, df)

        parsed_data = df.to_dict(orient="records")

        history = _save_history(
            db,
            current_user.user_id,
            file.filename,
            len(contents),
            "성공",
            content_hash,
        )
        _save_raw_inventory(db, current_user.user_id, history.id, df)

        return {
            "status": "success",
            "filename": file.filename,
            "total_rows": len(parsed_data),
            "data_preview": parsed_data
        }

    except HTTPException:
        raise
    except ValueError:
        logger.exception("업로드 데이터 검증 중 오류 발생")
        db.rollback()
        try:
            _save_history(db, current_user.user_id, file.filename, 0, "실패")
        except Exception:
            db.rollback()
            logger.exception("업로드 실패 이력 저장 중 추가 오류 발생")
        raise HTTPException(
            status_code=400,
            detail="업로드 데이터 형식이 올바르지 않습니다. 입력 파일을 확인해주세요."
        )
    except Exception:
        logger.exception("업로드 처리 중 오류 발생")
        db.rollback()
        try:
            _save_history(db, current_user.user_id, file.filename, 0, "실패")
        except Exception:
            db.rollback()
            logger.exception("업로드 실패 이력 저장 중 추가 오류 발생")
        raise HTTPException(
            status_code=500,
            detail="업로드 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
        )


def _save_analysis_results(db: Session, user_id: int, upload_batch_id: str, df: pd.DataFrame) -> None:
    """분석 결과를 raw_inventory/analysis_results 테이블에 저장해 대시보드/재고 목록 API가 조회할 수 있게 한다."""
    for _, row in df.iterrows():
        raw_item = RawInventory(
            user_id=user_id,
            upload_batch_id=upload_batch_id,
            product_name=row["product_name"],
            stock_qty=int(row["stock_qty"]),
            purchase_price=float(row["purchase_price"]),
            market_price=float(row["selling_price"]),
            inbound_date=row["received_date"].date(),
            created_at=datetime.utcnow(),
        )
        db.add(raw_item)
        db.flush()

        db.add(AnalysisResult(
            item_id=raw_item.item_id,
            sales_velocity=float(row["sales_speed"]),
            aging_days=int(row["storage_days"]),
            days_to_sell=int(min(row["days_to_sell"], 9999)),
            risk_grade=row["risk_grade"],
            inventory_amount=float(row["inventory_value"]),
            final_score=float(row["final_score"]),
            fluctuation_rate=float(row["depreciation_rate"]),
            updated_at=datetime.utcnow(),
        ))

    db.commit()


def _save_history(
    db: Session,
    user_id: int,
    filename: str,
    file_size: int,
    status: str,
    content_hash: str | None = None,
) -> UploadHistory:
    history = UploadHistory(
        user_id=user_id,
        file_name=filename,
        size=file_size,
        status=status,
        content_hash=content_hash,
    )
    db.add(history)
    db.commit()
    db.refresh(history)
    return history


def _save_raw_inventory(db: Session, user_id: int, batch_id: int, df: pd.DataFrame) -> None:
    """업로드된 엑셀 행들을 raw_inventory와 analysis_results 테이블에 함께 저장한다."""
    # analyze_inventory()가 컬럼명을 영문으로 변환한 뒤의 df를 받는다.
    now = datetime.utcnow()
    raw_rows = [
        RawInventory(
            user_id=user_id,
            upload_batch_id=str(batch_id),
            product_name=row["product_name"],
            stock_qty=int(row["stock_qty"]),
            purchase_price=row["purchase_price"],
            market_price=row["selling_price"],
            inbound_date=row["received_date"].date(),
            created_at=now,
            sales_qty=int(row["sales_qty"]),
        )
        for _, row in df.iterrows()
    ]
    db.add_all(raw_rows)
    db.flush()  # analysis_results가 참조할 item_id를 커밋 전에 미리 확보한다.

    analysis_rows = [
        AnalysisResult(
            item_id=raw_row.item_id,
            sales_velocity=row["sales_speed"],
            aging_days=int(row["storage_days"]),
            days_to_sell=int(round(row["days_to_sell"])),
            inventory_amount=row["inventory_value"],
            fluctuation_rate=row["depreciation_rate"],
            updated_at=now,
        )
        for raw_row, (_, row) in zip(raw_rows, df.iterrows())
    ]
    db.add_all(analysis_rows)
    db.commit()


# -------------------- 업로드 기록 조회/삭제 API (로그인한 사용자 본인 기록만) --------------------
@app.get("/api/history")
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


@app.delete("/api/history/{history_id}")
def delete_history(
    history_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
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


@app.delete("/api/history")
def clear_history(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    db.query(UploadHistory).filter(UploadHistory.user_id == current_user.user_id).delete()
    db.commit()
    return {"status": "success"}


# -------------------- 분석 결과 조회 API (대시보드/재고 목록/전략/내보내기) --------------------
def _query_user_analysis(db: Session, user_id: int):
    return (
        db.query(AnalysisResult, RawInventory)
        .join(RawInventory, AnalysisResult.item_id == RawInventory.item_id)
        .filter(RawInventory.user_id == user_id)
    )


@app.get("/api/dashboard")
def get_dashboard(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = _query_user_analysis(db, current_user.user_id).all()

    if not rows:
        return {
            "total_sku": 0,
            "risk_count": 0,
            "aging_count": 0,
            "monthly_saving": 0,
            "grades": [],
            "risk_items": [],
        }

    grade_counts: dict[str, int] = {}
    risk_count = 0
    aging_count = 0
    monthly_saving = 0.0

    for analysis, _ in rows:
        grade_counts[analysis.risk_grade] = grade_counts.get(analysis.risk_grade, 0) + 1
        if analysis.risk_grade in ("위험", "처분 권장"):
            risk_count += 1
            # 처분 권장/위험 재고를 정리했을 때 회수 가능한 재고금액의 10%를 월 절감액으로 추정
            monthly_saving += float(analysis.inventory_amount or 0) * 0.1
        if analysis.aging_days >= 60:
            aging_count += 1

    risk_items = sorted(
        (
            {"product_name": item.product_name, "final_score": analysis.final_score}
            for analysis, item in rows
        ),
        key=lambda x: x["final_score"],
        reverse=True,
    )[:5]

    return {
        "total_sku": len(rows),
        "risk_count": risk_count,
        "aging_count": aging_count,
        "monthly_saving": round(monthly_saving),
        "grades": [
            {"name": name, "count": count, "color": RISK_GRADE_META.get(name, {}).get("color", "#64748b")}
            for name, count in grade_counts.items()
        ],
        "risk_items": risk_items,
    }


@app.get("/api/inventory")
def list_inventory(
    search: str = "",
    status: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = _query_user_analysis(db, current_user.user_id)
    if search:
        query = query.filter(RawInventory.product_name.contains(search))
    if status:
        query = query.filter(AnalysisResult.risk_grade == status)

    rows = query.order_by(AnalysisResult.final_score.desc()).all()

    return {
        "items": [
            {
                "item_id": item.item_id,
                "product_name": item.product_name,
                "stock_qty": item.stock_qty,
                "aging_days": analysis.aging_days,
                "days_to_sell": analysis.days_to_sell,
                "risk_grade": analysis.risk_grade,
                "action_plans": analysis.action_plans,
            }
            for analysis, item in rows
        ]
    }


@app.get("/api/inventory/{item_id}")
def get_inventory_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = _query_user_analysis(db, current_user.user_id).filter(RawInventory.item_id == item_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="해당 재고를 찾을 수 없습니다.")

    analysis, item = row
    return {
        "item_id": item.item_id,
        "product_name": item.product_name,
        "stock_qty": item.stock_qty,
        "aging_days": analysis.aging_days,
        "days_to_sell": analysis.days_to_sell,
        "risk_grade": analysis.risk_grade,
        "ai_diagnosis": analysis.ai_diagnosis,
    }


@app.get("/api/strategy")
def get_strategy(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = (
        db.query(AnalysisResult.risk_grade, func.count(AnalysisResult.result_id))
        .join(RawInventory, AnalysisResult.item_id == RawInventory.item_id)
        .filter(RawInventory.user_id == current_user.user_id)
        .group_by(AnalysisResult.risk_grade)
        .all()
    )

    groups = [
        {
            "type": grade,
            "title": RISK_GRADE_META.get(grade, {}).get("title", grade),
            "summary": RISK_GRADE_META.get(grade, {}).get("summary", ""),
            "count": count,
        }
        for grade, count in rows
    ]

    return {"groups": groups}


@app.get("/api/export")
def get_export(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = _query_user_analysis(db, current_user.user_id).order_by(AnalysisResult.final_score.desc()).all()

    items = [
        {
            "item_id": item.item_id,
            "product_name": item.product_name,
            "stock_qty": item.stock_qty,
            "aging_days": analysis.aging_days,
            "risk_grade": analysis.risk_grade,
            "action_plans": analysis.action_plans,
        }
        for analysis, item in rows
    ]

    return {
        "summary": f"총 {len(items)}개 품목의 재고 분석 리포트입니다.",
        "items": items,
    }


# -------------------- 정적 HTML/CSS/JavaScript 페이지 연결 --------------------
# 위의 명시적 라우트("/", "/api/...")에 안 걸린 나머지 경로를
# static 폴더에서 파일명 그대로 서빙
app.mount("/js", StaticFiles(directory="js"), name="js")
app.mount("/", StaticFiles(directory="static"), name="static")
