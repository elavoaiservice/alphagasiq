import pytest
from quant_service.models import (
    LinearRegressionModel,
    NaivePersistenceModel,
    NotImplementedModel,
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


class TestRegistry:
    def test_implemented_types_are_exactly_naive_and_linear(self):
        assert set(implemented_model_types()) == {ModelType.NAIVE_PERSISTENCE, ModelType.LINEAR_REGRESSION}

    def test_build_model_returns_correct_type(self):
        assert isinstance(build_model(ModelType.NAIVE_PERSISTENCE), NaivePersistenceModel)
        assert isinstance(build_model(ModelType.LINEAR_REGRESSION), LinearRegressionModel)

    def test_build_model_returns_not_implemented_for_unbuilt_types(self):
        for mt in (ModelType.ARIMA, ModelType.VAR, ModelType.STATE_SPACE, ModelType.RANDOM_FOREST,
                   ModelType.XGBOOST, ModelType.LIGHTGBM, ModelType.TEMPORAL_FUSION_TRANSFORMER, ModelType.LSTM):
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
        assert implemented == {"NAIVE_PERSISTENCE", "LINEAR_REGRESSION"}
