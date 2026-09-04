"""SIMULATED daily Henry Hub spot price history for backtesting.

Deliberately includes a once-every-10-days "late revision" (publication_time lags
observation_time by 2 days instead of the normal same-day settlement lag) so that
`as_of_filter`'s point-in-time correctness is actually exercised, not just defined —
see `tests/quant/test_backtesting.py` for the regression test this enables.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

from schemas import DataClassification, TimeSeriesObservation

SEED_RNG_KEY = "alphagasiq-quant-price-history-v1"
MEAN_REVERSION_SPEED = 0.03
DAILY_VOLATILITY = 0.045
NORMAL_PUBLICATION_LAG_HOURS = 20
LATE_REVISION_EVERY_N_DAYS = 10
LATE_REVISION_LAG_DAYS = 2


def generate_price_history(*, end_date: date, num_days: int = 250, base_price: float = 3.0) -> list[TimeSeriesObservation]:
    rng = random.Random(SEED_RNG_KEY)
    observations: list[TimeSeriesObservation] = []
    price = base_price
    for i in range(num_days, 0, -1):
        day = end_date - timedelta(days=i)
        price += MEAN_REVERSION_SPEED * (base_price - price) + rng.gauss(0, DAILY_VOLATILITY)
        price = max(0.5, price)

        observation_time = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=14, minutes=30)
        day_index = num_days - i
        if day_index > 0 and day_index % LATE_REVISION_EVERY_N_DAYS == 0:
            publication_time = observation_time + timedelta(days=LATE_REVISION_LAG_DAYS)
        else:
            publication_time = observation_time + timedelta(hours=NORMAL_PUBLICATION_LAG_HOURS)

        observations.append(
            TimeSeriesObservation(
                source="MOCK_CME",
                source_type=DataClassification.SIMULATED,
                series_id="NG.HH.SPOT.DAILY",
                symbol="NG-HH-SPOT",
                commodity="NATURAL_GAS",
                category="PRICE",
                sub_category="SPOT_SETTLEMENT",
                geography="US",
                location="HENRY_HUB",
                value=round(price, 4),
                unit="USD_MMBTU",
                observation_time=observation_time,
                publication_time=publication_time,
            )
        )
    return observations
