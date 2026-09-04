from __future__ import annotations

import warnings

import numpy as np
from schemas import ModelType
from statsmodels.tsa.arima.model import ARIMA

from .base import ForecastModel


class ARIMAModel(ForecastModel):
    """Real ARIMA(p,d,q) via `statsmodels`. Order defaults to (2,1,0) — a
    general-purpose choice for a non-stationary price-like series (first-differenced
    to stationarity, two AR terms, no MA term) — with a fallback ladder to simpler
    orders for the short/near-degenerate training windows walk-forward backtesting can
    produce, so one hard-to-fit fold doesn't take down the whole backtest. The MA-free
    orders are also a deliberate performance choice: this platform's automatic
    research cycle walk-forward-backtests ARIMA across dozens of folds on every run,
    and dropping the MA term roughly halves each fit's cost (no separate MA
    optimization in the Kalman filter MLE) with no change to correctness — it is a
    genuinely different, still-valid ARIMA specification, not a shortcut around one.
    """

    model_type = ModelType.ARIMA
    version = "1.0.0"

    _ORDER_LADDER = [(2, 1, 0), (1, 1, 0), (0, 1, 0)]

    def __init__(self) -> None:
        self._result = None

    def fit(self, x: list[float], y: list[float]) -> None:
        if len(y) < 4:
            raise ValueError("ARIMAModel needs at least 4 points to fit")
        y_arr = np.asarray(y, dtype=float)
        last_error: Exception | None = None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for order in self._ORDER_LADDER:
                try:
                    self._result = ARIMA(y_arr, order=order).fit()
                    return
                except Exception as exc:  # statsmodels raises varying LinAlgError/ValueError types on ill-conditioned short series
                    last_error = exc
                    continue
        raise RuntimeError(f"ARIMAModel failed to fit under any order in {self._ORDER_LADDER}: {last_error}")

    def predict(self, steps_ahead: int) -> float:
        if self._result is None:
            raise RuntimeError("Model must be fit() before predict()")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            forecast = self._result.forecast(steps=steps_ahead)
        return float(forecast[-1])

    def predict_with_uncertainty(self, steps_ahead: int) -> tuple[float, float]:
        if self._result is None:
            raise RuntimeError("Model must be fit() before predict()")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            forecast_result = self._result.get_forecast(steps=steps_ahead)
        return float(forecast_result.predicted_mean[-1]), float(forecast_result.se_mean[-1])
