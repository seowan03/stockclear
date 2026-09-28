from datetime import date

from pydantic import BaseModel, Field


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


class InventoryInput(BaseModel):
    product_name: str = Field(min_length=1, max_length=255)
    stock_qty: int = Field(ge=0)
    purchase_price: float = Field(ge=0)
    received_date: date
    selling_price: float = Field(ge=0)
    sales_qty: int = Field(ge=0)
