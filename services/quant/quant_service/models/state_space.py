from __future__ import annotations

import warnings

import numpy as np
from schemas import ModelType
from statsmodels.tsa.statespace.structural import UnobservedComponents

from .base import ForecastModel


class StateSpaceModel(ForecastModel):
    """Real state-space model: a local-level (random walk + noise) Kalman-filter
    model via `statsmodels.tsa.statespace.structural.UnobservedComponents`. "Local
    level" (rather than "local linear trend") is deliberate: it has only one state to
    estimate, which stays numerically stable on the short training windows (as few as
    ~60 points) walk-forward backtesting uses, where a trend component would often be
    poorly identified and destabilize the Kalman filter.
    """

    model_type = ModelType.STATE_SPACE
    version = "1.0.0"

    def __init__(self) -> None:
        self._result = None

    def fit(self, x: list[float], y: list[float]) -> None:
        if len(y) < 4:
            raise ValueError("StateSpaceModel needs at least 4 points to fit")
        y_arr = np.asarray(y, dtype=float)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._result = UnobservedComponents(y_arr, level="local level").fit(disp=False)

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
