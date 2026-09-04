"""Multi-horizon forecast engine (docs/architecture.md FORECAST ENGINE).

Wraps a fitted `ForecastModel` to produce the canonical `PriceForecast` output. The
platform's daily-resolution seed data means the sub-daily horizons (1h/4h) are honest
approximations — same model, scaled step size — rather than genuinely intraday
forecasts; that limitation is surfaced in `drivers` rather than hidden.
"""

from __future__ import annotations

import math

from schemas import ForecastHorizon, PriceForecast

from .models.base import ForecastModel

HORIZON_STEPS_DAYS: dict[ForecastHorizon, float] = {
    ForecastHorizon.ONE_HOUR: 1 / 24,
    ForecastHorizon.FOUR_HOUR: 4 / 24,
    ForecastHorizon.ONE_DAY: 1,
    ForecastHorizon.THREE_DAY: 3,
    ForecastHorizon.SEVEN_DAY: 7,
    ForecastHorizon.THIRTY_DAY: 30,
    ForecastHorizon.SEASONAL: 90,
}

_SUB_DAILY_HORIZONS = {ForecastHorizon.ONE_HOUR, ForecastHorizon.FOUR_HOUR}


def generate_forecast(
    *,
    model: ForecastModel,
    instrument: str,
    horizon: ForecastHorizon,
    current_price: float,
    drivers: list[str] | None = None,
    model_contributions: dict[str, float] | None = None,
) -> PriceForecast:
    steps_ahead = HORIZON_STEPS_DAYS[horizon]
    price_forecast, expected_volatility = model.predict_with_uncertainty(steps_ahead)
    return_forecast = price_forecast - current_price

    up_probability = _direction_probability(return_forecast, expected_volatility)
    down_probability = round(1.0 - up_probability, 4)

    confidence = _confidence_from_volatility(expected_volatility, current_price)
    if not model.is_implemented:
        confidence = 0.0

    resolved_drivers = list(drivers or [])
    if horizon in _SUB_DAILY_HORIZONS:
        resolved_drivers.append(
            "Sub-daily horizon approximated from the platform's daily-resolution seed data; "
            "treat as directional guidance only, not an intraday-calibrated forecast."
        )

    return PriceForecast(
        instrument=instrument,
        horizon=horizon,
        price_forecast=round(price_forecast, 4),
        return_forecast=round(return_forecast, 4),
        up_probability=up_probability,
        down_probability=down_probability,
        expected_volatility=round(expected_volatility, 4),
        confidence=confidence,
        drivers=resolved_drivers,
        model_contributions=model_contributions or {model.model_type.value: 1.0},
    )


_NEGLIGIBLE_VOLATILITY = 1e-9  # a noiseless fit's residual std lands here (floating-point
# noise around zero, e.g. 1.8e-15), not at exact 0.0 -- `<= 0` alone doesn't catch it and
# lets `z = return_forecast / expected_volatility` blow up into an unbounded float that
# overflows `math.exp(-z)`.


def _direction_probability(return_forecast: float, expected_volatility: float) -> float:
    if expected_volatility <= _NEGLIGIBLE_VOLATILITY:
        if return_forecast > 0:
            return 1.0
        if return_forecast < 0:
            return 0.0
        return 0.5
    z = return_forecast / expected_volatility
    # Clamp as a hard safety net regardless of the guard above: the sigmoid is already
    # saturated to 0.0/1.0 (at 4-decimal rounding) well before |z| reaches 700, the point
    # where math.exp(-z) would overflow a float.
    z = max(-700.0, min(700.0, z))
    return round(1 / (1 + math.exp(-z)), 4)


def _confidence_from_volatility(expected_volatility: float, current_price: float) -> float:
    if current_price <= 0:
        return 0.5
    relative_vol = expected_volatility / current_price
    # Heuristic: tighter relative volatility -> higher confidence, floor/ceiling at
    # [0.3, 0.9] so this never claims false certainty or total uselessness.
    confidence = 0.9 - min(0.6, relative_vol * 4)
    return round(max(0.3, confidence), 3)
