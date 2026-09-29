import math

import numpy as np

MOCK_MARKET_PRICE_MIN_FACTOR = 0.9
MOCK_MARKET_PRICE_MAX_FACTOR = 1.1
MOCK_MARKET_PRICE_STEP = 100


def generate_mock_market_price(
    selling_price: object,
    rng: np.random.Generator | None = None,
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
    if minimum_step <= maximum_step:
        return int(generator.integers(minimum_step, maximum_step + 1) * MOCK_MARKET_PRICE_STEP)

    return int(generator.integers(minimum_price, maximum_price + 1))