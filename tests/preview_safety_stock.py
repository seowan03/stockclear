import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["ENV"] = "development"

import uvicorn
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database as database
import app.security as security
from app.main import app
from app.models import AnalysisResult, InventoryDailyMetric, RawInventory, UploadHistory, User
from app.routers import auth


def prepare_preview():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    database.engine = engine
    database.SessionLocal = sessionmaker(bind=engine)
    database.Base.metadata.create_all(engine)
    security.SESSION_COOKIE_NAME = "stockclear_preview_user"
    auth.SESSION_COOKIE_NAME = security.SESSION_COOKIE_NAME
    with database.SessionLocal() as db:
        db.add(User(user_id=1, username="Safety Stock Preview", email="preview@example.test", created_at=datetime.now()))
        db.add(UploadHistory(id=1, user_id=1, file_name="Safety stock test samples", size=0, status="성공"))
        db.flush()
        for item_id, name, stock, average, grade in [
            (1, "테스트 무선 마우스", 30, 4, "주의"),
            (2, "테스트 키보드", 12, 1.2, "위험"),
        ]:
            db.add(RawInventory(
                item_id=item_id, user_id=1, upload_file_id=1, product_name=name,
                stock_qty=stock, purchase_price=10000, market_price=15000,
                mock_market_price=14500, inbound_date=date(2026, 9, 1), sales_qty=int(average * 30),
            ))
            db.add(AnalysisResult(
                item_id=item_id, sales_velocity=average, aging_days=30,
                days_to_sell=10, risk_grade=grade, inventory_amount=stock * 10000,
                final_score=30, fluctuation_rate=0,
            ))
            for offset in range(30):
                db.add(InventoryDailyMetric(
                    item_id=item_id,
                    business_date=date.today() - timedelta(days=offset + 1),
                    daily_sales_qty=(10 if item_id == 1 else 6) if offset % 2 else 0,
                    daily_selling_price=15000,
                    price_variation_rate=0,
                ))
        db.commit()

    @app.middleware("http")
    async def preview_session(request, call_next):
        response = await call_next(request)
        security.set_session_cookie(response, 1)
        return response


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8011)
    options = parser.parse_args()
    prepare_preview()
    uvicorn.run(app, host="127.0.0.1", port=options.port)