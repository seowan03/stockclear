import hashlib
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

import numpy as np
from sqlalchemy.orm import Session

from app.models import InventoryDailyMetric

DAILY_METRIC_DAYS = 31
DAILY_METRIC_GENERATION_VERSION = "v1"
PRICE_VARIATION_MIN = -0.05
PRICE_VARIATION_MAX = 0.05


def generate_daily_inventory_metrics(
    user_id: int,
    item_id: int,
    inbound_date: date,
    base_selling_price: object,
) -> list[InventoryDailyMetric]:
    base_price = Decimal(str(base_selling_price or 0))
    if not base_price.is_finite() or base_price < 0:
        base_price = Decimal("0")

    metrics = []
    for day_offset in range(DAILY_METRIC_DAYS):
        business_date = inbound_date + timedelta(days=day_offset)
        seed_material = (
            f"{DAILY_METRIC_GENERATION_VERSION}:{user_id}:{item_id}:"
            f"{business_date.isoformat()}:{base_price.normalize()}"
        )
        seed = int.from_bytes(hashlib.sha256(seed_material.encode("utf-8")).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        daily_sales_qty = int(rng.integers(0, 21))
        requested_variation = float(rng.uniform(PRICE_VARIATION_MIN, PRICE_VARIATION_MAX))

        if base_price == 0:
            daily_selling_price = Decimal("0")
            applied_variation = Decimal("0")
        else:
            variation_factor = Decimal(str(1 + requested_variation))
            rounded_price = (base_price * variation_factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            minimum_price = int((base_price * Decimal("0.95")).quantize(Decimal("1"), rounding=ROUND_CEILING))
            maximum_price = int((base_price * Decimal("1.05")).quantize(Decimal("1"), rounding=ROUND_FLOOR))

            if minimum_price <= maximum_price:
                daily_selling_price = Decimal(str(max(minimum_price, min(maximum_price, int(rounded_price)))))
            else:
                daily_selling_price = base_price.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            applied_variation = ((daily_selling_price / base_price) - Decimal("1")).quantize(
                Decimal("0.00001"),
                rounding=ROUND_HALF_UP,
            )

        metrics.append(InventoryDailyMetric(
            item_id=item_id,
            business_date=business_date,
            daily_sales_qty=daily_sales_qty,
            daily_selling_price=daily_selling_price,
            price_variation_rate=applied_variation,
        ))
    return metrics


def replace_daily_inventory_metrics(
    db: Session,
    user_id: int,
    item_id: int,
    inbound_date: date,
    base_selling_price: object,
) -> None:
    db.query(InventoryDailyMetric).filter(
        InventoryDailyMetric.item_id == item_id,
    ).delete(synchronize_session=False)
    db.add_all(generate_daily_inventory_metrics(
        user_id,
        item_id,
        inbound_date,
        base_selling_price,
    ))