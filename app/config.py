import os

from dotenv import load_dotenv

load_dotenv()

KAKAO_CLIENT_ID = os.getenv("KAKAO_CLIENT_ID")
KAKAO_CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET")
KAKAO_REDIRECT_URI = os.getenv(
    "KAKAO_REDIRECT_URI",
    "http://127.0.0.1:8000/api/auth/kakao/callback",
)

MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_BODY_SIZE_BYTES = MAX_UPLOAD_SIZE_BYTES + (1024 * 1024)
MAX_UPLOAD_ROWS = 50_000
UPLOAD_READ_CHUNK_SIZE = 1024 * 1024

CORS_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]

RISK_GRADE_META = {
    "정상": {"color": "#10b981", "title": "정상 운영 대상", "summary": "현재 재고 운영 상태가 양호합니다."},
    "주의": {"color": "#f59e0b", "title": "모니터링 대상", "summary": "안전재고 수준을 벗어나기 전 지속적인 관찰이 필요합니다."},
    "위험": {"color": "#ef4444", "title": "할인 프로모션 대상", "summary": "결품/체류 위험이 있어 할인 및 프로모션 검토가 필요합니다."},
    "처분 권장": {"color": "#a855f7", "title": "즉시 처분 대상", "summary": "회전율이 낮고 감가가 심해 빠른 재고 소진이 필요합니다."},
}
