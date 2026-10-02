import math

import numpy as np

MOCK_MARKET_PRICE_MIN_FACTOR = 0.9
MOCK_MARKET_PRICE_MAX_FACTOR = 1.1
MOCK_MARKET_PRICE_STEP = 100


def generate_mock_market_price(
    selling_price: object,
    rng: np.random.Generator | None = None,
    previous_price: object | None = None,
) -> int | None:
    try:
        price = float(selling_price)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(price) or price <= 0:
        return None

    minimum_price = math.ceil(price * MOCK_MARKET_PRICE_MIN_FACTOR)
    maximum_price = math.floor(price * MOCK_MARKET_PRICE_MAX_FACTOR)
    if minimum_price > maximum_price:
        return None

    generator = rng if rng is not None else np.random.default_rng()
    minimum_step = math.ceil(minimum_price / MOCK_MARKET_PRICE_STEP)
    maximum_step = math.floor(maximum_price / MOCK_MARKET_PRICE_STEP)

    try:
        previous = float(previous_price) if previous_price is not None else None
    except (TypeError, ValueError):
        previous = None

    if minimum_step <= maximum_step:
        if previous is not None and math.isfinite(previous):
            previous_step = previous / MOCK_MARKET_PRICE_STEP
            if previous_step.is_integer() and minimum_step <= previous_step <= maximum_step:
                step_count = maximum_step - minimum_step + 1
                if step_count > 1:
                    offset = int(generator.integers(0, step_count - 1))
                    previous_offset = int(previous_step) - minimum_step
                    if offset >= previous_offset:
                        offset += 1
                    return int((minimum_step + offset) * MOCK_MARKET_PRICE_STEP)
            else:
                return int(generator.integers(minimum_step, maximum_step + 1) * MOCK_MARKET_PRICE_STEP)

    if previous is not None and math.isfinite(previous) and previous.is_integer():
        previous_integer = int(previous)
        if minimum_price <= previous_integer <= maximum_price:
            price_count = maximum_price - minimum_price + 1
            if price_count <= 1:
                return None
            offset = int(generator.integers(0, price_count - 1))
            previous_offset = previous_integer - minimum_price
            if offset >= previous_offset:
                offset += 1
            return minimum_price + offset

    if minimum_step <= maximum_step:
        return int(generator.integers(minimum_step, maximum_step + 1) * MOCK_MARKET_PRICE_STEP)

    return int(generator.integers(minimum_price, maximum_price + 1))