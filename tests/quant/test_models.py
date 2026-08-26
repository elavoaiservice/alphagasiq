import math

import pytest
from quant_service.models import (
    ARIMAModel,
    LightGBMModel,
    LinearRegressionModel,
    NaivePersistenceModel,
    NotImplementedModel,
    RandomForestModel,
    StateSpaceModel,
    VARModel,
    XGBoostModel,
    all_model_status,
    build_model,
    implemented_model_types,
)
from schemas import ModelType


class TestNaivePersistenceModel:
    def test_predicts_last_value_regardless_of_horizon(self):
        m = NaivePersistenceModel()
        m.fit(list(range(5)), [1.0, 2.0, 3.0, 4.0, 5.0])
        assert m.predict(1) == 5.0
        assert m.predict(30) == 5.0

    def test_uncertainty_grows_with_horizon(self):
        m = NaivePersistenceModel()
        m.fit(list(range(10)), [1.0, 1.2, 0.9, 1.3, 1.0, 1.4, 1.1, 1.5, 1.2, 1.6])
        _, vol_short = m.predict_with_uncertainty(1)
        _, vol_long = m.predict_with_uncertainty(10)
        assert vol_long > vol_short

    def test_raises_on_empty_series(self):
        m = NaivePersistenceModel()
        with pytest.raises(ValueError):
            m.fit([], [])

    def test_raises_if_predict_before_fit(self):
        m = NaivePersistenceModel()
        with pytest.raises(RuntimeError):
            m.predict(1)


class TestLinearRegressionModel:
    def test_fits_a_perfect_line_exactly(self):
        m = LinearRegressionModel()
        x = list(range(10))  # last x = 9
        y = [2.0 * xi + 3.0 for xi in x]
        m.fit(x, y)
        assert m.predict(0) == pytest.approx(2.0 * 9 + 3.0)  # 0 steps ahead = the last fitted point
        assert m.predict(1) == pytest.approx(2.0 * 10 + 3.0)  # one step past x=9 -> x=10
        assert m.predict(5) == pytest.approx(2.0 * 14 + 3.0)

    def test_residual_std_is_zero_for_perfect_fit(self):
        m = LinearRegressionModel()
        x = list(range(10))
        y = [2.0 * xi for xi in x]
        m.fit(x, y)
        _, vol = m.predict_with_uncertainty(1)
        assert vol == pytest.approx(0.0, abs=1e-9)

    def test_residual_std_positive_for_noisy_data(self):
        m = LinearRegressionModel()
        x = list(range(6))
        y = [1.0, 3.0, 2.0, 5.0, 4.0, 6.0]
        m.fit(x, y)
        _, vol = m.predict_with_uncertainty(1)
        assert vol > 0

    def test_raises_on_mismatched_lengths(self):
        m = LinearRegressionModel()
        with pytest.raises(ValueError):
            m.fit([1, 2, 3], [1, 2])

    def test_raises_on_too_few_points(self):
        m = LinearRegressionModel()
        with pytest.raises(ValueError):
            m.fit([1], [1])

    def test_raises_if_predict_before_fit(self):
        m = LinearRegressionModel()
        with pytest.raises(RuntimeError):
            m.predict(1)


_IMPLEMENTED_TYPES = {
    ModelType.NAIVE_PERSISTENCE,
    ModelType.LINEAR_REGRESSION,
    ModelType.ARIMA,
    ModelType.VAR,
    ModelType.STATE_SPACE,
    ModelType.RANDOM_FOREST,
    ModelType.XGBOOST,
    ModelType.LIGHTGBM,
}
_STILL_UNIMPLEMENTED_TYPES = {ModelType.TEMPORAL_FUSION_TRANSFORMER, ModelType.LSTM}


class TestRegistry:
    def test_implemented_types_cover_every_model_but_deep_learning(self):
        assert set(implemented_model_types()) == _IMPLEMENTED_TYPES

    def test_build_model_returns_correct_type(self):
        assert isinstance(build_model(ModelType.NAIVE_PERSISTENCE), NaivePersistenceModel)
        assert isinstance(build_model(ModelType.LINEAR_REGRESSION), LinearRegressionModel)
        assert isinstance(build_model(ModelType.ARIMA), ARIMAModel)
        assert isinstance(build_model(ModelType.VAR), VARModel)
        assert isinstance(build_model(ModelType.STATE_SPACE), StateSpaceModel)
        assert isinstance(build_model(ModelType.RANDOM_FOREST), RandomForestModel)
        assert isinstance(build_model(ModelType.XGBOOST), XGBoostModel)
        assert isinstance(build_model(ModelType.LIGHTGBM), LightGBMModel)

    def test_build_model_returns_not_implemented_for_unbuilt_types(self):
        for mt in _STILL_UNIMPLEMENTED_TYPES:
            model = build_model(mt)
            assert isinstance(model, NotImplementedModel)
            assert model.is_implemented is False
            with pytest.raises(NotImplementedError):
                model.fit([1, 2], [1, 2])
            with pytest.raises(NotImplementedError):
                model.predict(1)

    def test_all_model_status_covers_every_model_type(self):
        statuses = all_model_status()
        assert len(statuses) == len(ModelType)
        implemented = {s["model_type"] for s in statuses if s["implemented"]}
        assert implemented == {mt.value for mt in _IMPLEMENTED_TYPES}
        not_implemented = {s["model_type"] for s in statuses if not s["implemented"]}
        assert not_implemented == {mt.value for mt in _STILL_UNIMPLEMENTED_TYPES}


def _synthetic_series(n: int = 60) -> tuple[list[float], list[float]]:
    x = list(range(n))
    y = [3.0 + 0.02 * i + 0.15 * math.sin(i / 3) for i in x]
    return x, y


@pytest.mark.parametrize(
    "model_cls",
    [ARIMAModel, VARModel, StateSpaceModel, RandomForestModel, XGBoostModel, LightGBMModel],
)
class TestRealAdvancedModels:
    """Every model registered as `implemented` must actually behave like a fit
    forecasting model: fitting must not raise, predictions must be finite real
    numbers (not NaN/inf from a silently-failed fit), longer horizons must still
    produce a value, and predict-before-fit must fail loudly rather than return a
    fabricated number."""

    def test_fits_and_predicts_a_finite_value(self, model_cls):
        x, y = _synthetic_series()
        model = model_cls()
        model.fit(x, y)
        forecast = model.predict(5)
        assert math.isfinite(forecast)

    def test_predict_with_uncertainty_returns_finite_nonnegative_volatility(self, model_cls):
        x, y = _synthetic_series()
        model = model_cls()
        model.fit(x, y)
        point, vol = model.predict_with_uncertainty(3)
        assert math.isfinite(point)
        assert math.isfinite(vol)
        assert vol >= 0

    def test_longer_horizon_still_predicts(self, model_cls):
        x, y = _synthetic_series()
        model = model_cls()
        model.fit(x, y)
        assert math.isfinite(model.predict(10))

    def test_raises_if_predict_before_fit(self, model_cls):
        model = model_cls()
        with pytest.raises(RuntimeError):
            model.predict(1)

    def test_raises_on_too_few_points(self, model_cls):
        model = model_cls()
        with pytest.raises(ValueError):
            model.fit([0, 1], [1.0, 2.0])

    def test_version_and_type_are_set(self, model_cls):
        model = model_cls()
        assert model.is_implemented is True
        assert isinstance(model.version, str) and model.version
        assert model.model_type in ModelType


class TestWalkForwardEvaluateWithRealModels:
    """The whole point of every model sharing the same `fit(x, y)`/`predict(steps)`
    interface is that `walk_forward_evaluate` can backtest any of them identically —
    this proves the new models actually plug into that pipeline, not just their own
    unit tests."""

    def test_walk_forward_evaluate_runs_for_every_implemented_model(self):
        from datetime import datetime, timedelta, timezone

        from quant_service.backtesting import walk_forward_evaluate
        from schemas import DataClassification, ForecastHorizon, TimeSeriesObservation

        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        observations = [
            TimeSeriesObservation(
                source="TEST",
                source_type=DataClassification.SIMULATED,
                series_id="test-price",
                symbol="NGZ26",
                commodity="NATURAL_GAS",
                category="PRICE",
                value=3.0 + 0.01 * i + 0.1 * math.sin(i / 4),
                unit="USD_MMBTU",
                observation_time=start + timedelta(days=i),
                publication_time=start + timedelta(days=i),
            )
            for i in range(120)
        ]
        for mt in _IMPLEMENTED_TYPES:
            result = walk_forward_evaluate(
                model_type=mt,
                observations=observations,
                instrument="NGZ26",
                horizon=ForecastHorizon.ONE_DAY,
                train_window_days=30,
                step_days=10,
            )
            assert result.n_folds > 0
            assert math.isfinite(result.mae)
            assert math.isfinite(result.rmse)
