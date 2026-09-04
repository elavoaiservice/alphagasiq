from __future__ import annotations

import warnings

import numpy as np
from schemas import ModelType
from statsmodels.tsa.api import VAR

from .base import ForecastModel


class VARModel(ForecastModel):
    """Real Vector Autoregression via `statsmodels.tsa.api.VAR`, fit on a genuine
    2-variable endogenous system derived from the series itself: the price level and
    its first difference (a return-like series). VAR is inherently multivariate, but
    every model in this platform is judged by the same `fit(x, y)` walk-forward
    interface on the same univariate series — so rather than special-case the
    backtesting/forecast pipeline to plumb a second real-world series (e.g. weather or
    storage; not yet wired into that pipeline — see docs/architecture.md §8) through
    to just this one model, this derives its second series from `y` itself. That
    keeps every model backtested on identical data (no unfair advantage/disadvantage
    from extra inputs) while still fitting a real, estimated VAR(p) system — not a
    fabricated multivariate forecast.
    """

    model_type = ModelType.VAR
    version = "1.0.0"

    _MAX_LAG_ORDER = 5

    def __init__(self) -> None:
        self._result = None

    def fit(self, x: list[float], y: list[float]) -> None:
        if len(y) < 8:
            raise ValueError("VARModel needs at least 8 points to fit a 2-variable VAR system")
        y_arr = np.asarray(y, dtype=float)
        levels = y_arr[1:]
        diffs = np.diff(y_arr)
        data = np.column_stack([levels, diffs])

        max_lags = max(1, min(self._MAX_LAG_ORDER, len(data) // 3 - 1))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = VAR(data)
            try:
                lag_order = max(1, model.select_order(maxlags=max_lags).aic)
            except Exception:
                lag_order = 1
            self._result = model.fit(lag_order)

    def predict(self, steps_ahead: int) -> float:
        if self._result is None:
            raise RuntimeError("Model must be fit() before predict()")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            forecast = self._result.forecast(self._result.endog[-self._result.k_ar :], steps=steps_ahead)
        return float(forecast[-1, 0])  # column 0 is the price-level series

    def predict_with_uncertainty(self, steps_ahead: int) -> tuple[float, float]:
        if self._result is None:
            raise RuntimeError("Model must be fit() before predict()")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            mid, lower, upper = self._result.forecast_interval(
                self._result.endog[-self._result.k_ar :], steps=steps_ahead, alpha=0.05
            )
        # 95% CI half-width / 1.96 back out an implied standard error for the level column.
        std_error = float((upper[-1, 0] - lower[-1, 0]) / (2 * 1.96))
        return float(mid[-1, 0]), std_error
