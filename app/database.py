import os
from urllib.parse import quote_plus
import numpy as np
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import DATABASE_URL, DB_CHARSET, DB_HOST, DB_NAME, DB_PASSWORD, DB_PORT, DB_USER
from app.services.mock_market_price import generate_mock_market_price

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


def ensure_upload_files_user_id_column():
    """
    upload_files 테이블이 이미 존재하는(수동 생성된) 환경에서는
    create_all이 컬럼을 추가해주지 않으므로, user_id 컬럼이 없으면 직접 ALTER TABLE로 추가한다.
    """
    inspector = inspect(engine)
    if "upload_files" not in inspector.get_table_names():
        return
    columns = [col["name"] for col in inspector.get_columns("upload_files")]
    if "user_id" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE upload_files ADD COLUMN user_id INT NULL"))

    if "content_hash" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE upload_files ADD COLUMN content_hash VARCHAR(64) NULL"))


def ensure_raw_inventory_is_deleted_column():
    inspector = inspect(engine)
    if "raw_inventory" not in inspector.get_table_names():
        return
    columns = [col["name"] for col in inspector.get_columns("raw_inventory")]
    if "is_deleted" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE raw_inventory ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT 0"))


def ensure_upload_analysis_summary_data_column():
    inspector = inspect(engine)
    if "upload_analysis_summaries" not in inspector.get_table_names():
        return
    columns = [col["name"] for col in inspector.get_columns("upload_analysis_summaries")]
    if "summary_data" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE upload_analysis_summaries ADD COLUMN summary_data TEXT NULL"))


def ensure_raw_inventory_upload_file_id_column():
    """
    raw_inventory 테이블에 upload_file_id 컬럼과 외래키(FK)가 없을 경우 안전하게 추가
    """
    inspector = inspect(engine)
    if "raw_inventory" not in inspector.get_table_names():
        return
    columns = [col["name"] for col in inspector.get_columns("raw_inventory")]
    if "upload_file_id" not in columns:
        with engine.begin() as conn:
            # 1. 컬럼 추가 (데이터 보존을 위해 NULL 허용)
            conn.execute(text("ALTER TABLE raw_inventory ADD COLUMN upload_file_id INT NULL"))
            # 2. Foreign Key 제약조건 추가
            conn.execute(
                text(
                    "ALTER TABLE raw_inventory "
                    "ADD CONSTRAINT fk_raw_inventory_upload_file_id "
                    "FOREIGN KEY (upload_file_id) REFERENCES upload_files(id) ON DELETE SET NULL"
                )
            )


def ensure_raw_inventory_mock_market_price_column():
    inspector = inspect(engine)
    if "raw_inventory" not in inspector.get_table_names():
        return
    columns = [col["name"] for col in inspector.get_columns("raw_inventory")]
    if "mock_market_price" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE raw_inventory ADD COLUMN mock_market_price NUMERIC(12, 2) NULL"))

    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT item_id, market_price FROM raw_inventory "
            "WHERE mock_market_price IS NULL AND market_price > 0"
        )).fetchall()
        rng = np.random.default_rng()
        updates = [
            {
                "item_id": row.item_id,
                "mock_market_price": generate_mock_market_price(row.market_price, rng),
            }
            for row in rows
        ]
        if updates:
            conn.execute(
                text(
                    "UPDATE raw_inventory SET mock_market_price = :mock_market_price "
                    "WHERE item_id = :item_id AND mock_market_price IS NULL"
                ),
                updates,
            )


def ensure_analysis_results_recommended_price_column():
    inspector = inspect(engine)
    if "analysis_results" not in inspector.get_table_names():
        return
    columns = [col["name"] for col in inspector.get_columns("analysis_results")]
    if "recommended_price" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE analysis_results ADD COLUMN recommended_price NUMERIC(12, 2) NULL"))


def init_db():
    """
    startup 시 호출할 통합 DB 초기화 함수.
    테이블 생성 및 모든 컬럼 보정(Helper)을 한 번에 실행함.
    """
    Base.metadata.create_all(bind=engine)
    ensure_upload_files_user_id_column()
    ensure_raw_inventory_is_deleted_column()
    ensure_upload_analysis_summary_data_column()
    ensure_raw_inventory_upload_file_id_column()  # 신규 컬럼 보정 구문
    ensure_raw_inventory_mock_market_price_column()
    ensure_analysis_results_recommended_price_column()