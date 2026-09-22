from fastapi import HTTPException, Request, UploadFile

from app.config import (
    MAX_UPLOAD_BODY_SIZE_BYTES,
    MAX_UPLOAD_SIZE_BYTES,
    UPLOAD_READ_CHUNK_SIZE,
)


def check_upload_content_length(request: Request) -> None:
    content_length = request.headers.get("content-length")
    if not content_length:
        return
    try:
        request_size = int(content_length)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="업로드 요청 크기 정보가 올바르지 않습니다.") from exc
    if request_size > MAX_UPLOAD_BODY_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="업로드 요청 크기가 허용 범위를 초과했습니다.")


async def read_upload_file_with_limit(file: UploadFile) -> bytes:
    chunks: list[bytes] = []
    total_size = 0

    while True:
        chunk = await file.read(UPLOAD_READ_CHUNK_SIZE)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(status_code=413, detail="파일 용량은 10MB를 초과할 수 없습니다.")
        chunks.append(chunk)

    if total_size == 0:
        raise HTTPException(status_code=400, detail="빈 파일은 업로드할 수 없습니다.")
    return b"".join(chunks)


def detect_csv_encoding(contents: bytes) -> str:
    for encoding in ("utf-8-sig", "cp949"):
        try:
            contents.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    raise HTTPException(status_code=400, detail="파일 내용이 CSV 형식이 아닙니다.")


def validate_upload_file_signature(filename: str, contents: bytes) -> str | None:
    normalized_filename = filename.lower()
    if normalized_filename.endswith(".xlsx"):
        if not contents.startswith(b"PK"):
            raise HTTPException(status_code=400, detail="파일 내용이 XLSX 형식이 아닙니다.")
        return None
    if normalized_filename.endswith(".xls"):
        if not contents.startswith(b"\xd0\xcf\x11\xe0"):
            raise HTTPException(status_code=400, detail="파일 내용이 XLS 형식이 아닙니다.")
        return None
    return detect_csv_encoding(contents)
