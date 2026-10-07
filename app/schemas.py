from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class InventoryGridEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: int = Field(gt=0)
    version: int = Field(gt=0)
    product_name: str = Field(min_length=1, max_length=255)
    stock_qty: int = Field(ge=0, strict=True)
    purchase_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2, allow_inf_nan=False)
    received_date: date
    selling_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2, allow_inf_nan=False)
    sales_qty: int = Field(ge=0, strict=True)

    @field_validator("product_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("상품명을 입력해 주세요.")
        return name

    @field_validator("received_date")
    @classmethod
    def check_received_date(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("미래 입고일은 입력할 수 없습니다.")
        return value


class InventoryGridBatchUpdate(BaseModel):
    items: list[InventoryGridEdit] = Field(min_length=1, max_length=500)


class SafetyStockCalculation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_daily_sales: float = Field(ge=0, le=1_000_000, allow_inf_nan=False)
    average_daily_sales: float = Field(ge=0, le=1_000_000, allow_inf_nan=False)
    max_lead_time_days: float = Field(default=5, ge=0, le=365, allow_inf_nan=False)
    average_lead_time_days: float = Field(default=2, ge=0, le=365, allow_inf_nan=False)

    @model_validator(mode="after")
    def check_averages(self):
        if self.average_daily_sales > self.max_daily_sales:
            raise ValueError("평균 일판매량은 최대 일판매량보다 클 수 없습니다.")
        if self.average_lead_time_days > self.max_lead_time_days:
            raise ValueError("평균 조달 기간은 최대 조달 기간보다 클 수 없습니다.")
        return self


# 판매사이트 내보내기 시 재고의 판매 여부를 갱신하는 요청 body 규격
class InventorySellingUpdate(BaseModel):
    is_selling: bool


class InventorySellingBatchUpdate(BaseModel):
    item_ids: list[int]
    is_selling: bool = True


# /api/ai-diagnose 요청 body를 검증하는 Pydantic 데이터 규격
class InventoryItem(BaseModel):
    product_name: str
    stock_qty: int
    purchase_price: int
    received_date: str
    selling_price: int
    sales_qty: int

    storage_days: int
    inventory_value: int
    sales_speed: float
    days_to_sell: float
    depreciation_rate: float
    mock_market_price: int | None = None