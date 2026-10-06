import os

from dotenv import load_dotenv

load_dotenv()

ENV = os.getenv("ENV", "development")

DATABASE_URL = os.getenv("DATABASE_URL")
DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER", "avnadmin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "defaultdb")
DB_PORT = os.getenv("DB_PORT", "21018")
DB_CHARSET = os.getenv("DB_CHARSET", "utf8mb4")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
KAKAO_CLIENT_ID = os.getenv("KAKAO_CLIENT_ID")
KAKAO_CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET")
KAKAO_REDIRECT_URI = os.getenv("KAKAO_REDIRECT_URI", "http://127.0.0.1:8000/api/auth/kakao/callback")
SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY")
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
    "장기": {"color": "#f97316", "title": "장기 관리 대상", "summary": "보관기간과 위험점수를 확인해 재고 회전 개선을 검토합니다."},
    "악성": {"color": "#ef4444", "title": "우선 조치 대상", "summary": "위험점수가 높아 우선적인 재고 조치가 필요합니다."},
}
