from fastapi import FastAPI, UploadFile, File, HTTPException
import pandas as pd
import io
from app.analysis import analyze_inventory

app = FastAPI(title="StockClear Backend", version="1.0")


# --- 엑셀 업로드 및 파싱 API ---
@app.post("/api/upload")
async def upload_and_parse_excel(file: UploadFile = File(...)):

    # 파일 확장자 검사
    if not file.filename.endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(
            status_code=400,
            detail="엑셀 파일(.xlsx, .xls) 또는 CSV 파일만 업로드 가능합니다."
        )

    try:
        # 파일 내용을 메모리에서 읽어오기
        contents = await file.read()

        # Excel 또는 CSV 읽기
        if file.filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(contents))
        else:
            df = pd.read_csv(io.BytesIO(contents))

        # 필수 컬럼
        required_columns = [
            "상품명",
            "재고량",
            "원가",
            "입고일",
            "판매가",
            "판매량"
        ]

        # 누락된 컬럼 확인
        missing_columns = [
            col for col in required_columns
            if col not in df.columns
        ]

        if missing_columns:
            raise HTTPException(
                status_code=400,
                detail=f"필수 컬럼이 없습니다: {missing_columns}"
            )
        # Pandas를 이용한 재고 분석
        df = analyze_inventory(df)
        # DataFrame → 딕셔너리 리스트
        parsed_data = df.to_dict(orient="records")

        return {
            "status": "success",
            "filename": file.filename,
            "total_rows": len(parsed_data),
            "data_preview": parsed_data
        }

    except HTTPException:
        # 우리가 직접 만든 400 오류는 그대로 전달
        raise

    except Exception as e:
        # 실제 파일 읽기 등의 예상하지 못한 오류
        raise HTTPException(
            status_code=500,
            detail=f"엑셀 파싱 중 에러 발생: {str(e)}"
        )


# router.py 연결
from app.router import router

app.include_router(router)