from app.database import Base
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Boolean,
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
  upload_file_id = Column(Integer, ForeignKey("upload_files.id"), nullable=True)
  product_name = Column(String(255))
  stock_qty = Column(Integer)
  purchase_price = Column(Numeric(12, 2))
  market_price = Column(Numeric(12, 2))
  mock_market_price = Column(Numeric(12, 2), nullable=True)
  inbound_date = Column(Date)
  created_at = Column(DateTime)
  sales_qty = Column(Integer)
  is_selling = Column(Boolean, nullable=False, default=False, server_default="0")
  is_deleted = Column(Boolean, nullable=False, default=False, server_default="0")


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
  content_hash = Column(String(64), nullable=True)


class UploadAnalysisSummary(Base):
  __tablename__ = "upload_analysis_summaries"

  summary_id = Column(Integer, primary_key=True, autoincrement=True)
  upload_id = Column(Integer, ForeignKey("upload_files.id"), nullable=False, unique=True)
  user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
  status = Column(String(20), nullable=False)
  summary_text = Column(Text)
  summary_data = Column(Text)
  generated_at = Column(DateTime, server_default=func.now())


class StrategyAction(Base):
  __tablename__ = "strategy_actions"

  action_id = Column(Integer, primary_key=True, autoincrement=True)
  user_id = Column(Integer, ForeignKey("users.user_id"), nullable=False)
  action_type = Column(String(30), nullable=False)
  status = Column(String(30), nullable=False, default="기록됨")
  item_ids = Column(Text, nullable=False)
  created_at = Column(DateTime, server_default=func.now())
