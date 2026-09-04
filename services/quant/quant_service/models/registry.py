"""Model registry: every model type docs/architecture.md names, with an honest flag
for whether it's actually implemented yet. Mirrors the `NotImplementedProvider`
pattern in `packages/data-sdk` — an unbuilt model shows up as unimplemented in
`/system` rather than being silently absent from the roster.
"""

from __future__ import annotations

from schemas import ModelType

from .arima import ARIMAModel
from .base import ForecastModel, NotImplementedModel
from .linear import LinearRegressionModel
from .naive import NaivePersistenceModel
from .state_space import StateSpaceModel
from .tree_ensemble import LightGBMModel, RandomForestModel, XGBoostModel
from .var import VARModel

_BUILDERS: dict[ModelType, type[ForecastModel]] = {
    ModelType.NAIVE_PERSISTENCE: NaivePersistenceModel,
    ModelType.LINEAR_REGRESSION: LinearRegressionModel,
    ModelType.ARIMA: ARIMAModel,
    ModelType.VAR: VARModel,
    ModelType.STATE_SPACE: StateSpaceModel,
    ModelType.RANDOM_FOREST: RandomForestModel,
    ModelType.XGBOOST: XGBoostModel,
    ModelType.LIGHTGBM: LightGBMModel,
}


def build_model(model_type: ModelType) -> ForecastModel:
    """Fresh, unfit model instance for the given type."""
    builder = _BUILDERS.get(model_type)
    if builder is not None:
        return builder()
    return NotImplementedModel(model_type)


def implemented_model_types() -> list[ModelType]:
    return list(_BUILDERS.keys())


def all_model_status() -> list[dict]:
    implemented = set(implemented_model_types())
    return [{"model_type": mt.value, "implemented": mt in implemented} for mt in ModelType]
