from app.database import Base
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
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
  version = Column(Integer, nullable=False, default=1, server_default="1")
  edited_at = Column(DateTime, nullable=True)


class InventoryDailyMetric(Base):
  __tablename__ = "inventory_daily_metrics"
  __table_args__ = (
    UniqueConstraint("item_id", "business_date", name="uq_inventory_daily_item_date"),
    Index("ix_inventory_daily_business_date", "business_date"),
  )

  metric_id = Column(Integer, primary_key=True, autoincrement=True)
  item_id = Column(Integer, ForeignKey("raw_inventory.item_id", ondelete="CASCADE"), nullable=False)
  business_date = Column(Date, nullable=False)
  daily_sales_qty = Column(Integer, nullable=False)
  remaining_stock_qty = Column(Integer, nullable=True)
  daily_selling_price = Column(Numeric(12, 2), nullable=False)
  price_variation_rate = Column(Numeric(7, 5), nullable=False)
  generated_at = Column(DateTime, server_default=func.now(), nullable=False)


class InventoryMonthlySale(Base):
  __tablename__ = "inventory_monthly_sales"
  __table_args__ = (
    UniqueConstraint("item_id", "month_start", "source_type", name="uq_inventory_monthly_item_month_source"),
  )

  monthly_id = Column(Integer, primary_key=True, autoincrement=True)
  item_id = Column(Integer, ForeignKey("raw_inventory.item_id", ondelete="CASCADE"), nullable=False)
  month_start = Column(Date, nullable=False)
  source_type = Column(String(20), nullable=False)
  total_sales_qty = Column(Integer, nullable=False)
  recorded_days = Column(Integer, nullable=False)
  aggregated_at = Column(DateTime, server_default=func.now(), nullable=False)


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
  recommended_price = Column(Numeric(12, 2), nullable=True)
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


class CustomerInquiry(Base):
  __tablename__ = "customer_inquiries"

  inquiry_id = Column(Integer, primary_key=True, autoincrement=True)
  user_id = Column(Integer, ForeignKey("users.user_id"), nullable=True)
  inquiry_type = Column(String(30), nullable=False)
  subject = Column(String(50), nullable=False)
  content = Column(Text, nullable=False)
  created_at = Column(DateTime, server_default=func.now(), nullable=False)
