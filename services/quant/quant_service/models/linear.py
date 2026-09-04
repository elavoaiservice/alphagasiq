from __future__ import annotations

import numpy as np
from schemas import ModelType

from .base import ForecastModel


class LinearRegressionModel(ForecastModel):
    """Ordinary least squares trend model: y = a + b*x, closed-form via numpy (no
    scikit-learn dependency needed for something this simple). Extrapolates the fitted
    trend `steps_ahead` periods past the end of the training window."""

    model_type = ModelType.LINEAR_REGRESSION
    version = "1.0.0"

    def __init__(self) -> None:
        self._slope: float | None = None
        self._intercept: float | None = None
        self._last_x: float | None = None
        self._residual_std: float = 0.0

    def fit(self, x: list[float], y: list[float]) -> None:
        if len(x) != len(y):
            raise ValueError("x and y must be the same length")
        if len(x) < 2:
            raise ValueError("LinearRegressionModel needs at least 2 points to fit")
        x_arr = np.asarray(x, dtype=float)
        y_arr = np.asarray(y, dtype=float)
        slope, intercept = np.polyfit(x_arr, y_arr, deg=1)
        self._slope = float(slope)
        self._intercept = float(intercept)
        self._last_x = float(x_arr[-1])
        residuals = y_arr - (slope * x_arr + intercept)
        self._residual_std = float(np.std(residuals)) if len(residuals) >= 2 else 0.0

    def predict(self, steps_ahead: int) -> float:
        if self._slope is None or self._intercept is None or self._last_x is None:
            raise RuntimeError("Model must be fit() before predict()")
        future_x = self._last_x + steps_ahead
        return self._slope * future_x + self._intercept

    def predict_with_uncertainty(self, steps_ahead: int) -> tuple[float, float]:
        return self.predict(steps_ahead), self._residual_std
