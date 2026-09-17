from app.database import Base
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.sql import func


# ORM 모델 정의
class User(Base):
  __tablename__ = "users"

  user_id = Column(Integer, primary_key=True, autoincrement=True)
  username = Column(String(255))
  email = Column(String(255))
  password_hash = Column(String(255))
  created_at = Column(DateTime)


class RawInventory(Base):
  __tablename__ = "raw_inventory"

  item_id = Column(Integer, primary_key=True, autoincrement=True)
  user_id = Column(Integer, ForeignKey("users.user_id"))
  upload_batch_id = Column(String(255))
  product_name = Column(String(255))
  stock_qty = Column(Integer)
  purchase_price = Column(Numeric(12, 2))
  market_price = Column(Numeric(12, 2))
  inbound_date = Column(Date)
  created_at = Column(DateTime)


class AnalysisResult(Base):
  __tablename__ = "analysis_results"

  result_id = Column(Integer, primary_key=True, autoincrement=True)
  item_id = Column(Integer, ForeignKey("raw_inventory.item_id"))
  sales_velocity = Column(Float)
  aging_days = Column(Integer)
  days_to_sell = Column(Integer)
  risk_grade = Column(String(50))
  inventory_amount = Column(Numeric(14, 2))
  final_score = Column(Float)
  fluctuation_rate = Column(Float)
  ai_diagnosis = Column(Text)
  action_plans = Column(Text)
  updated_at = Column(DateTime)


class UploadHistory(Base):
  __tablename__ = "upload_files"

  id = Column(Integer, primary_key=True, autoincrement=True)
  user_id = Column(Integer, ForeignKey("users.user_id"), nullable=True)
  upload_date = Column(DateTime, server_default=func.now())
  file_name = Column(String(255))
  size = Column(Integer)  # bytes
  status = Column(String(50))  # 성공 / 실패 / 보관됨
