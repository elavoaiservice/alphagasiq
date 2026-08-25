"""Model registry: every model type docs/architecture.md names, with an honest flag
for whether it's actually implemented yet. Mirrors the `NotImplementedProvider`
pattern in `packages/data-sdk` — an unbuilt model shows up as unimplemented in
`/system` rather than being silently absent from the roster.
"""

from __future__ import annotations

from schemas import ModelType

from .base import ForecastModel, NotImplementedModel
from .linear import LinearRegressionModel
from .naive import NaivePersistenceModel

_UNIMPLEMENTED_TYPES = [
    ModelType.ARIMA,
    ModelType.VAR,
    ModelType.STATE_SPACE,
    ModelType.RANDOM_FOREST,
    ModelType.XGBOOST,
    ModelType.LIGHTGBM,
    ModelType.TEMPORAL_FUSION_TRANSFORMER,
    ModelType.LSTM,
]


def build_model(model_type: ModelType) -> ForecastModel:
    """Fresh, unfit model instance for the given type."""
    if model_type == ModelType.NAIVE_PERSISTENCE:
        return NaivePersistenceModel()
    if model_type == ModelType.LINEAR_REGRESSION:
        return LinearRegressionModel()
    return NotImplementedModel(model_type)


def implemented_model_types() -> list[ModelType]:
    return [ModelType.NAIVE_PERSISTENCE, ModelType.LINEAR_REGRESSION]


def all_model_status() -> list[dict]:
    implemented = set(implemented_model_types())
    return [{"model_type": mt.value, "implemented": mt in implemented} for mt in ModelType]
