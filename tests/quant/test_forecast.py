import pytest
from quant_service.forecast import _direction_probability, generate_forecast
from quant_service.models import build_model
from schemas import ForecastHorizon, ModelType


def fitted_model(prices: list[float]) -> "ForecastModel":
    m = build_model(ModelType.LINEAR_REGRESSION)
    m.fit(list(range(len(prices))), prices)
    return m


class TestGenerateForecast:
    def test_uptrend_forecast_has_positive_return_and_high_up_probability(self):
        prices = [1.0 + 0.1 * i for i in range(20)]  # noiseless uptrend
        model = fitted_model(prices)
        result = generate_forecast(model=model, instrument="NGQ26", horizon=ForecastHorizon.SEVEN_DAY, current_price=prices[-1])
        assert result.return_forecast > 0
        assert result.up_probability == 1.0  # zero residual std -> deterministic direction
        assert result.down_probability == 0.0

    def test_downtrend_forecast_has_negative_return(self):
        prices = [10.0 - 0.1 * i for i in range(20)]
        model = fitted_model(prices)
        result = generate_forecast(model=model, instrument="NGQ26", horizon=ForecastHorizon.ONE_DAY, current_price=prices[-1])
        assert result.return_forecast < 0
        assert result.up_probability == 0.0

    def test_confidence_is_bounded(self):
        prices = [3.0 + (0.5 if i % 2 == 0 else -0.5) for i in range(20)]  # noisy
        model = fitted_model(prices)
        result = generate_forecast(model=model, instrument="NGQ26", horizon=ForecastHorizon.SEVEN_DAY, current_price=prices[-1])
        assert 0.3 <= result.confidence <= 0.9

    def test_sub_daily_horizon_flags_the_limitation_in_drivers(self):
        prices = [3.0 + 0.01 * i for i in range(20)]
        model = fitted_model(prices)
        result = generate_forecast(model=model, instrument="NGQ26", horizon=ForecastHorizon.ONE_HOUR, current_price=prices[-1])
        assert any("daily-resolution" in d for d in result.drivers)

    def test_daily_horizon_does_not_carry_the_sub_daily_caveat(self):
        prices = [3.0 + 0.01 * i for i in range(20)]
        model = fitted_model(prices)
        result = generate_forecast(model=model, instrument="NGQ26", horizon=ForecastHorizon.SEVEN_DAY, current_price=prices[-1])
        assert not any("daily-resolution" in d for d in result.drivers)

    def test_model_contributions_default_to_single_model_full_weight(self):
        prices = [3.0] * 10
        model = fitted_model(prices)
        result = generate_forecast(model=model, instrument="NGQ26", horizon=ForecastHorizon.ONE_DAY, current_price=3.0)
        assert result.model_contributions == {"LINEAR_REGRESSION": 1.0}

    def test_unimplemented_model_forces_zero_confidence(self):
        from quant_service.models.base import NotImplementedModel

        model = NotImplementedModel(ModelType.ARIMA)
        model._fitted = True  # bypass fit() since it raises
        model.predict = lambda steps_ahead: 3.0  # type: ignore[method-assign]
        model.predict_with_uncertainty = lambda steps_ahead: (3.0, 0.1)  # type: ignore[method-assign]
        result = generate_forecast(model=model, instrument="NGQ26", horizon=ForecastHorizon.ONE_DAY, current_price=3.0)
        assert result.confidence == 0.0


class TestDirectionProbability:
    """A noiseless model fit (perfectly linear input, e.g. a constant trend) produces
    a residual std that lands as floating-point noise around zero (e.g. 1.8e-15), not
    exact 0.0 -- these exercise that edge directly rather than relying on a specific
    model fit to happen to reproduce it."""

    def test_negligible_positive_volatility_treated_as_zero_downtrend(self):
        assert _direction_probability(-0.1, 1.8e-15) == 0.0

    def test_negligible_positive_volatility_treated_as_zero_uptrend(self):
        assert _direction_probability(0.1, 1.8e-15) == 1.0

    def test_negligible_positive_volatility_treated_as_zero_flat(self):
        assert _direction_probability(0.0, 1.8e-15) == 0.5

    def test_extreme_z_clamped_instead_of_overflowing(self):
        # Above the negligible-volatility threshold, but still small enough that
        # z = return_forecast / expected_volatility is large enough to overflow
        # math.exp(-z) without the clamp.
        assert _direction_probability(-0.1, 1e-8) == 0.0
        assert _direction_probability(0.1, 1e-8) == 1.0

    def test_normal_volatility_unaffected(self):
        # A real, non-negligible volatility still produces a genuine sigmoid value,
        # not a hard 0.0/1.0 clamp.
        result = _direction_probability(0.05, 0.1)
        assert 0.5 < result < 1.0
