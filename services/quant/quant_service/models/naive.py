from __future__ import annotations

import statistics

from schemas import ModelType

from .base import ForecastModel


class NaivePersistenceModel(ForecastModel):
    """The mandatory baseline: forecast = last observed value. Every other model in
    this platform must beat this on walk-forward metrics to be worth using — if it
    can't, `services/quant` should be reporting that fact, not hiding it."""

    model_type = ModelType.NAIVE_PERSISTENCE
    version = "1.0.0"

    def __init__(self) -> None:
        self._last_value: float | None = None
        self._residual_std: float = 0.0

    def fit(self, x: list[float], y: list[float]) -> None:
        if not y:
            raise ValueError("Cannot fit NaivePersistenceModel on an empty series")
        self._last_value = y[-1]
        # Residual std of a persistence forecast is just the std of period-over-period
        # changes — a simple, honest volatility estimate for this baseline.
        diffs = [y[i] - y[i - 1] for i in range(1, len(y))]
        self._residual_std = statistics.pstdev(diffs) if len(diffs) >= 2 else 0.0

    def predict(self, steps_ahead: int) -> float:
        if self._last_value is None:
            raise RuntimeError("Model must be fit() before predict()")
        return self._last_value

    def predict_with_uncertainty(self, steps_ahead: int) -> tuple[float, float]:
        # Random-walk assumption: uncertainty grows with sqrt(horizon).
        return self.predict(steps_ahead), self._residual_std * (steps_ahead**0.5)
