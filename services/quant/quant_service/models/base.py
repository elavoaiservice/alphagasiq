"""Model interface every forecasting model implements — from the trivial baseline
this MVP ships to the ARIMA/VAR/state-space/tree-ensemble/deep-learning models it only
defines an interface for (docs/architecture.md QUANTITATIVE PLATFORM). "Do NOT assume a
deep learning model is superior" is a design constraint, not a suggestion: every model
here is judged only by `walk_forward_evaluate()` metrics, never by architecture.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from schemas import ModelType


class ForecastModel(ABC):
    model_type: ModelType
    version: str = "0.1.0"
    is_implemented: bool = True

    @abstractmethod
    def fit(self, x: list[float], y: list[float]) -> None:
        """`x` is a time index (e.g. days since series start), `y` the target series
        (price or return) — deliberately univariate/simple for the MVP models; a
        multivariate model (VAR, state-space) would override this with a richer
        signature but keep the same `predict(steps_ahead)` contract."""
        ...

    @abstractmethod
    def predict(self, steps_ahead: int) -> float:
        """Point forecast `steps_ahead` periods beyond the end of the fitted series."""
        ...

    def predict_with_uncertainty(self, steps_ahead: int) -> tuple[float, float]:
        """(point_forecast, expected_volatility). Default: no uncertainty model, so
        volatility is reported as 0.0 — subclasses with a real error distribution
        (e.g. residual-based) should override this rather than silently claim false
        precision."""
        return self.predict(steps_ahead), 0.0


class NotImplementedModel(ForecastModel):
    """Placeholder for model types docs/architecture.md names but this MVP does not
    yet implement (ARIMA, VAR, state-space, Random Forest, XGBoost, LightGBM, TFT,
    LSTM). Raises clearly rather than silently returning a fabricated forecast."""

    is_implemented = False

    def __init__(self, model_type: ModelType):
        self.model_type = model_type

    def fit(self, x: list[float], y: list[float]) -> None:
        raise NotImplementedError(f"{self.model_type.value} is not yet implemented")

    def predict(self, steps_ahead: int) -> float:
        raise NotImplementedError(f"{self.model_type.value} is not yet implemented")
