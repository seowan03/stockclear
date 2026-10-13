from app.database import Base
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Boolean,
    BigInteger,
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
  username = Column(String(50), nullable=False)
  email = Column(String(255), nullable=False, unique=True)
  password_hash = Column(String(255), nullable=False)
  role = Column(String(20), nullable=False, default="user", server_default="user")
  created_at = Column(DateTime, server_default=func.now())


class RawInventory(Base):
  __tablename__ = "raw_inventory"
  __table_args__ = (
    Index("ix_raw_inventory_user_deleted", "user_id", "is_deleted"),
    Index("ix_raw_inventory_user_batch", "user_id", "upload_batch_id"),
  )

  item_id = Column(Integer, primary_key=True, autoincrement=True)
  user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE", name="fk_raw_inventory_user"), nullable=False)
  upload_batch_id = Column(String(100), nullable=False)
  upload_file_id = Column(Integer, ForeignKey("upload_files.id", ondelete="CASCADE", name="fk_raw_inventory_upload_file"), nullable=True)
  product_name = Column(String(255), nullable=False)
  stock_qty = Column(Integer, nullable=False, default=0, server_default="0")
  purchase_price = Column(Numeric(12, 2), nullable=False, default=0, server_default="0.00")
  market_price = Column(Numeric(12, 2), nullable=False, default=0, server_default="0.00")
  mock_market_price = Column(Numeric(12, 2), nullable=True)
  inbound_date = Column(Date, nullable=False)
  created_at = Column(DateTime, server_default=func.now())
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
  __table_args__ = (
    UniqueConstraint("item_id", name="uq_analysis_results_item_id"),
  )

  result_id = Column(Integer, primary_key=True, autoincrement=True)
  item_id = Column(Integer, ForeignKey("raw_inventory.item_id", ondelete="CASCADE", name="fk_raw_inventory_item"))
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
  diagnosis_input_hash = Column(String(64), nullable=True)
  diagnosis_cache = Column(Text, nullable=True)
  updated_at = Column(DateTime)


class UploadHistory(Base):
  __tablename__ = "upload_files"
  __table_args__ = (
    Index("ix_upload_files_user_date", "user_id", "upload_date"),
  )

  id = Column(Integer, primary_key=True, autoincrement=True)
  user_id = Column(Integer, ForeignKey("users.user_id", ondelete="CASCADE", name="fk_upload_files_user"), nullable=False)
  upload_date = Column(DateTime, server_default=func.now())
  file_name = Column(String(255), nullable=False)
  size = Column(BigInteger, default=0, server_default="0")  # bytes
  status = Column(String(50), nullable=False, default="PENDING", server_default="PENDING")
  content_hash = Column(String(64), nullable=True)


class UploadAnalysisSummary(Base):
  __tablename__ = "upload_analysis_summaries"
  __table_args__ = (
    Index("ix_upload_summaries_user_generated", "user_id", "generated_at"),
  )

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
  __table_args__ = (
    Index("ix_customer_inquiries_status_created", "status", "created_at"),
  )

  inquiry_id = Column(Integer, primary_key=True, autoincrement=True)
  user_id = Column(Integer, ForeignKey("users.user_id"), nullable=True)
  inquiry_type = Column(String(30), nullable=False)
  subject = Column(String(50), nullable=False)
  content = Column(Text, nullable=False)
  status = Column(String(20), nullable=False, default="접수", server_default="접수")
  admin_reply = Column(Text, nullable=True)
  replied_at = Column(DateTime, nullable=True)
  replied_by_user_id = Column(Integer, nullable=True)
  reply_token_hash = Column(String(64), nullable=True)
  created_at = Column(DateTime, server_default=func.now(), nullable=False)
