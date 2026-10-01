import hashlib
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

import numpy as np
from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from app.models import InventoryDailyMetric, InventoryMonthlySale, RawInventory, User

DAILY_METRIC_END_DATE = date(2026, 9, 30)
DAILY_METRIC_GENERATION_VERSION = "v1"
PRICE_VARIATION_MIN = -0.05
PRICE_VARIATION_MAX = 0.05
DEMO_SOURCE = "demo"


def inventory_archive_before(as_of_date: date) -> date:
    try:
        anniversary = as_of_date.replace(year=as_of_date.year - 1)
    except ValueError:
        anniversary = as_of_date.replace(year=as_of_date.year - 1, day=28)
    return anniversary.replace(day=1)


def inventory_today() -> date:
    return datetime.now(timezone(timedelta(hours=9))).date()


def generate_daily_inventory_metrics(
    user_id: int,
    item_id: int,
    inbound_date: date,
    base_selling_price: object,
    stock_qty: int,
) -> list[InventoryDailyMetric]:
    base_price = Decimal(str(base_selling_price or 0))
    if not base_price.is_finite() or base_price < 0:
        base_price = Decimal("0")

    metrics = []
    remaining_stock = max(0, int(stock_qty))
    days_to_generate = max(0, (DAILY_METRIC_END_DATE - inbound_date).days)
    for day_offset in range(1, days_to_generate + 1):
        business_date = inbound_date + timedelta(days=day_offset)
        seed_material = (
            f"{DAILY_METRIC_GENERATION_VERSION}:{user_id}:{item_id}:"
            f"{business_date.isoformat()}:{base_price.normalize()}"
        )
        seed = int.from_bytes(hashlib.sha256(seed_material.encode("utf-8")).digest()[:8], "big")
        rng = np.random.default_rng(seed)
        daily_sales_qty = min(int(rng.integers(0, 6)), max(0, remaining_stock - 1))
        remaining_stock -= daily_sales_qty
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
            remaining_stock_qty=remaining_stock,
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
    stock_qty: int,
    as_of_date: date | None = None,
) -> None:
    db.query(InventoryMonthlySale).filter(
        InventoryMonthlySale.item_id == item_id,
        InventoryMonthlySale.source_type == DEMO_SOURCE,
    ).delete(synchronize_session=False)
    db.query(InventoryDailyMetric).filter(
        InventoryDailyMetric.item_id == item_id,
    ).delete(synchronize_session=False)
    metrics = generate_daily_inventory_metrics(
        user_id,
        item_id,
        inbound_date,
        base_selling_price,
        stock_qty,
    )
    archive_before = inventory_archive_before(as_of_date or inventory_today())
    monthly = defaultdict(lambda: [0, 0])
    recent = []
    for metric in metrics:
        if metric.business_date < archive_before:
            month_start = metric.business_date.replace(day=1)
            monthly[month_start][0] += metric.daily_sales_qty
            monthly[month_start][1] += 1
        else:
            recent.append(metric)
    if recent:
        db.bulk_save_objects(recent)
    db.add_all(InventoryMonthlySale(
        item_id=item_id,
        month_start=month_start,
        source_type=DEMO_SOURCE,
        total_sales_qty=totals[0],
        recorded_days=totals[1],
    ) for month_start, totals in monthly.items())


def archive_inventory_daily_metrics(
    db: Session, user_id: int, as_of_date: date, batch_size: int = 100,
) -> dict[str, int]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    db.query(User).filter(User.user_id == user_id).with_for_update().first()
    archive_before = inventory_archive_before(as_of_date)
    item_ids = [row.item_id for row in db.query(InventoryDailyMetric.item_id).join(
        RawInventory, RawInventory.item_id == InventoryDailyMetric.item_id,
    ).filter(
        RawInventory.user_id == user_id,
        InventoryDailyMetric.business_date < archive_before,
    ).group_by(InventoryDailyMetric.item_id).order_by(InventoryDailyMetric.item_id).limit(batch_size).all()]
    if not item_ids:
        return {"items": 0, "months": 0, "daily_rows": 0}

    aggregates = db.query(
        InventoryDailyMetric.item_id,
        extract("year", InventoryDailyMetric.business_date).label("year"),
        extract("month", InventoryDailyMetric.business_date).label("month"),
        func.sum(InventoryDailyMetric.daily_sales_qty).label("sales"),
        func.count(InventoryDailyMetric.metric_id).label("days"),
    ).filter(
        InventoryDailyMetric.item_id.in_(item_ids),
        InventoryDailyMetric.business_date < archive_before,
    ).group_by(
        InventoryDailyMetric.item_id,
        extract("year", InventoryDailyMetric.business_date),
        extract("month", InventoryDailyMetric.business_date),
    ).all()
    for row in aggregates:
        month_start = date(int(row.year), int(row.month), 1)
        existing = db.query(InventoryMonthlySale).filter_by(
            item_id=row.item_id, month_start=month_start, source_type=DEMO_SOURCE,
        ).first()
        if existing and existing.recorded_days != int(row.days):
            raise ValueError(f"Monthly sales overlap for item {row.item_id}, month {month_start}")
        if existing is None:
            existing = InventoryMonthlySale(item_id=row.item_id, month_start=month_start, source_type=DEMO_SOURCE)
            db.add(existing)
        existing.total_sales_qty = int(row.sales)
        existing.recorded_days = int(row.days)
    db.flush()
    daily_rows = db.query(InventoryDailyMetric).filter(
        InventoryDailyMetric.item_id.in_(item_ids),
        InventoryDailyMetric.business_date < archive_before,
    ).delete(synchronize_session=False)
    if daily_rows != sum(int(row.days) for row in aggregates):
        raise ValueError("Daily sales changed during archival")
    return {"items": len(item_ids), "months": len(aggregates), "daily_rows": daily_rows}


def main() -> None:
    import argparse
    import json
    import sys
    from time import perf_counter

    from app.database import SessionLocal, init_db

    parser = argparse.ArgumentParser(description="Archive completed months of daily inventory sales")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None, help="YYYY-MM-DD (defaults to today's KST date)")
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")

    init_db()
    as_of_date = args.as_of or inventory_today()
    totals = {"items": 0, "months": 0, "daily_rows": 0}
    started_at = perf_counter()
    with SessionLocal() as db:
        user_ids = [row.user_id for row in db.query(User.user_id).order_by(User.user_id).all()]
        for user_id in user_ids:
            while True:
                try:
                    result = archive_inventory_daily_metrics(db, user_id, as_of_date, args.batch_size)
                    db.commit()
                except Exception as error:
                    db.rollback()
                    print(json.dumps({
                        "status": "failed",
                        "as_of_date": as_of_date.isoformat(),
                        "user_id": user_id,
                        "failed_batches": 1,
                        "processed": totals,
                        "error_type": type(error).__name__,
                    }), file=sys.stderr)
                    raise
                for key in totals:
                    totals[key] += result[key]
                if not result["items"]:
                    break
        remaining_eligible = db.query(InventoryDailyMetric).filter(
            InventoryDailyMetric.business_date < inventory_archive_before(as_of_date),
        ).count()
        daily_rows = db.query(InventoryDailyMetric).count()
        monthly_rows = db.query(InventoryMonthlySale).count()
    print(json.dumps({
        "status": "complete",
        "as_of_date": as_of_date.isoformat(),
        "batch_size": args.batch_size,
        "processed": totals,
        "remaining_eligible_daily_rows": remaining_eligible,
        "daily_rows": daily_rows,
        "monthly_rows": monthly_rows,
        "failed_batches": 0,
        "elapsed_seconds": round(perf_counter() - started_at, 3),
    }))


if __name__ == "__main__":
    main()