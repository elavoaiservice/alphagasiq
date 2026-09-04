"""tests/alpha/test_agent_alpha_score.py -- Agent Alpha Score(TM)'s deterministic
scoring engine. Table-driven, mirroring test_materiality.py's style: one class of
tests per scoring method, plus the boundary cases the docstring calls out (only
FORECASTING gets a genuine backtested figure; every other agent gets the
confidence-consistency proxy, never mislabeled as historical accuracy)."""

from __future__ import annotations

import pytest
from alpha_service.agent_alpha_score import (
    METHOD_BACKTESTED,
    METHOD_CONFIDENCE_PROXY,
    AgentAlphaScoreEngine,
)
from schemas import AgentType, BacktestResult, ForecastHorizon, ModelType, PriceForecast


def make_backtest(model_type: ModelType, directional_accuracy: float) -> BacktestResult:
    return BacktestResult(
        model_type=model_type,
        model_version="1.0.0",
        instrument="HENRY_HUB",
        horizon=ForecastHorizon.SEVEN_DAY,
        n_folds=10,
        mae=0.1,
        rmse=0.15,
        directional_accuracy=directional_accuracy,
        hit_rate=0.6,
        max_drawdown=0.1,
    )


def make_price_forecast(model_contributions: dict[str, float]) -> PriceForecast:
    return PriceForecast(
        instrument="HENRY_HUB",
        horizon=ForecastHorizon.SEVEN_DAY,
        price_forecast=3.2,
        return_forecast=0.05,
        up_probability=0.6,
        down_probability=0.4,
        expected_volatility=0.2,
        confidence=0.7,
        model_contributions=model_contributions,
    )


@pytest.fixture
def engine() -> AgentAlphaScoreEngine:
    return AgentAlphaScoreEngine()


class TestBacktestedScoring:
    def test_forecasting_agent_with_matching_backtest_gets_backtested_method(self, engine):
        forecast = make_price_forecast({"ARIMA": 1.0})
        backtests = {"ARIMA": make_backtest(ModelType.ARIMA, 0.7)}
        score = engine.score(
            AgentType.FORECASTING, price_forecast=forecast, latest_backtests=backtests
        )
        assert score.method == METHOD_BACKTESTED
        assert score.score == pytest.approx(70.0)

    def test_weighted_by_model_contributions(self, engine):
        forecast = make_price_forecast({"ARIMA": 0.75, "LINEAR_REGRESSION": 0.25})
        backtests = {
            "ARIMA": make_backtest(ModelType.ARIMA, 0.8),
            "LINEAR_REGRESSION": make_backtest(ModelType.LINEAR_REGRESSION, 0.4),
        }
        score = engine.score(
            AgentType.FORECASTING, price_forecast=forecast, latest_backtests=backtests
        )
        # 0.75*0.8 + 0.25*0.4 = 0.7 -> 70.0
        assert score.score == pytest.approx(70.0)

    def test_zero_or_negative_contribution_weight_is_excluded(self, engine):
        forecast = make_price_forecast({"ARIMA": 1.0, "LINEAR_REGRESSION": 0.0})
        backtests = {
            "ARIMA": make_backtest(ModelType.ARIMA, 0.9),
            "LINEAR_REGRESSION": make_backtest(ModelType.LINEAR_REGRESSION, 0.1),
        }
        score = engine.score(
            AgentType.FORECASTING, price_forecast=forecast, latest_backtests=backtests
        )
        assert score.score == pytest.approx(90.0)

    def test_no_matching_backtest_falls_back_to_confidence_proxy(self, engine):
        forecast = make_price_forecast({"UNKNOWN_MODEL": 1.0})
        backtests = {"ARIMA": make_backtest(ModelType.ARIMA, 0.9)}
        score = engine.score(
            AgentType.FORECASTING,
            price_forecast=forecast,
            latest_backtests=backtests,
            recent_confidences=[0.6],
        )
        assert score.method == METHOD_CONFIDENCE_PROXY

    def test_non_forecasting_agent_never_gets_backtested_method(self, engine):
        """Only the Forecasting agent has a genuine resolved-outcome ledger today --
        every other agent must never be mislabeled as backtested even if a
        PriceForecast/backtests happen to be passed in."""
        forecast = make_price_forecast({"ARIMA": 1.0})
        backtests = {"ARIMA": make_backtest(ModelType.ARIMA, 0.9)}
        score = engine.score(
            AgentType.STORAGE, price_forecast=forecast, latest_backtests=backtests
        )
        assert score.method == METHOD_CONFIDENCE_PROXY


class TestConfidenceConsistencyProxy:
    def test_no_recent_confidences_yields_neutral_default(self, engine):
        score = engine.score(AgentType.STORAGE)
        assert score.method == METHOD_CONFIDENCE_PROXY
        assert score.score == 50.0
        assert score.sample_size == 0

    def test_high_stable_confidence_scores_higher_than_low_erratic_confidence(self, engine):
        stable = engine.score(
            AgentType.STORAGE, recent_confidences=[0.9, 0.9, 0.9], has_citations_fraction=1.0
        )
        erratic = engine.score(
            AgentType.STORAGE, recent_confidences=[0.2, 0.9, 0.3], has_citations_fraction=0.0
        )
        assert stable.score > erratic.score

    def test_score_is_bounded_zero_to_hundred(self, engine):
        score = engine.score(AgentType.STORAGE, recent_confidences=[1.0, 1.0], has_citations_fraction=1.0)
        assert 0.0 <= score.score <= 100.0
        score2 = engine.score(AgentType.STORAGE, recent_confidences=[0.0, 0.0], has_citations_fraction=0.0)
        assert 0.0 <= score2.score <= 100.0

    def test_sample_size_matches_input_length(self, engine):
        score = engine.score(AgentType.STORAGE, recent_confidences=[0.5, 0.6, 0.7, 0.8])
        assert score.sample_size == 4

    def test_single_confidence_value_has_full_consistency(self, engine):
        score = engine.score(AgentType.STORAGE, recent_confidences=[0.5])
        assert score.components["consistency"] == 100.0
