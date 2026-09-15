import os
from urllib.parse import quote_plus
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# .env 파일에서 환경 변수 로드
load_dotenv()

# .env 파일의 개별 변수 추출
DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER", "avnadmin")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "defaultdb")
DB_PORT = os.getenv("DB_PORT", "21018")
DB_CHARSET = os.getenv("DB_CHARSET", "utf8mb4")

# 패스워드 특수문자 URL 인코딩 처리
ENCODED_PASSWORD = quote_plus(DB_PASSWORD) if DB_PASSWORD else ""

# DATABASE_URL이 지정되어 있다면 우선 사용하고, 없을 경우 .env 변수들로 동적 생성
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    DATABASE_URL = (
        f"mysql+pymysql://{DB_USER}:{ENCODED_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
        f"?charset={DB_CHARSET}"
    )

# SQLAlchemy 엔진 생성
# pool_pre_ping=True: 연결 끊김 방지 확인
# pool_recycle=3600: 1시간마다 커넥션 갱신
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False
)

# 세션 팩토리 생성 (autocommit/autoflush 비활성화)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ORM 모델 상속용 Base 클래스
Base = declarative_base()


def get_db():
    """
    데이터베이스 세션 생성 및 자동 해제를 위한 제너레이터 함수 (FastAPI/Flask 의존성 주입용).
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

