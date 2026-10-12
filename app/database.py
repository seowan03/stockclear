from urllib.parse import quote_plus
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import DATABASE_URL, DB_CHARSET, DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER

# 패스워드 특수문자 URL 인코딩 처리
ENCODED_PASSWORD = quote_plus(DB_PASSWORD) if DB_PASSWORD else ""

# DATABASE_URL이 지정되어 있다면 우선 사용하고, 없을 경우 설정값으로 동적 생성
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
