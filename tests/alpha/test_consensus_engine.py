"""tests/alpha/test_consensus_engine.py -- AlphaConsensus(TM)'s dynamically-weighted
aggregation of AgentForecasts into a single ConsensusView. Table-driven, mirroring
test_impact_engine.py's style."""

from __future__ import annotations

import pytest
from alpha_service.consensus_engine import ConsensusEngine
from schemas import AgentAlphaScore, AgentForecast, AgentType, SignalDirection


def make_forecast(agent_type: AgentType, direction: SignalDirection, **overrides) -> AgentForecast:
    defaults = dict(
        agent_id=f"{agent_type.value.lower()}-agent",
        agent_type=agent_type,
        agent_version="1.0.0",
        forecast_type="STORAGE_WEEKLY",
        target="STORAGE_BCF",
        forecast_value=-90.0,
        direction=direction,
        probability=0.6,
        confidence=0.7,
    )
    defaults.update(overrides)
    return AgentForecast(**defaults)


def make_score(agent_type: AgentType, score: float) -> AgentAlphaScore:
    return AgentAlphaScore(agent_type=agent_type, score=score, method="TEST", sample_size=1)


@pytest.fixture
def engine() -> ConsensusEngine:
    return ConsensusEngine()


class TestEmptyInput:
    def test_no_forecasts_returns_none(self, engine):
        result = engine.compute(consensus_type="MARKET_DIRECTION", target="STORAGE_BCF", forecasts=[], scores={})
        assert result is None


class TestWeighting:
    def test_higher_alpha_score_dominates_direction(self, engine):
        forecasts = [
            make_forecast(AgentType.STORAGE, SignalDirection.BULLISH, confidence=0.9),
            make_forecast(AgentType.WEATHER, SignalDirection.BEARISH, confidence=0.9),
        ]
        scores = {
            AgentType.STORAGE: make_score(AgentType.STORAGE, 95.0),
            AgentType.WEATHER: make_score(AgentType.WEATHER, 20.0),
        }
        view = engine.compute(consensus_type="MARKET_DIRECTION", target="STORAGE_BCF", forecasts=forecasts, scores=scores)
        assert view.bull_probability > view.bear_probability
        assert "STORAGE" in view.leading_agents

    def test_missing_score_falls_back_to_neutral_default_weight(self, engine):
        forecasts = [make_forecast(AgentType.STORAGE, SignalDirection.BULLISH)]
        view = engine.compute(consensus_type="MARKET_DIRECTION", target="STORAGE_BCF", forecasts=forecasts, scores={})
        assert view.agent_weights[0].alpha_score == 50.0

    def test_all_zero_confidence_falls_back_to_equal_weighting(self, engine):
        forecasts = [
            make_forecast(AgentType.STORAGE, SignalDirection.BULLISH, confidence=0.0),
            make_forecast(AgentType.WEATHER, SignalDirection.BEARISH, confidence=0.0),
        ]
        view = engine.compute(consensus_type="MARKET_DIRECTION", target="STORAGE_BCF", forecasts=forecasts, scores={})
        assert view.agent_weights[0].weight == pytest.approx(0.5)
        assert view.agent_weights[1].weight == pytest.approx(0.5)

    def test_weights_sum_to_one(self, engine):
        forecasts = [
            make_forecast(AgentType.STORAGE, SignalDirection.BULLISH),
            make_forecast(AgentType.WEATHER, SignalDirection.BEARISH),
            make_forecast(AgentType.SUPPLY, SignalDirection.NEUTRAL),
        ]
        scores = {
            AgentType.STORAGE: make_score(AgentType.STORAGE, 80.0),
            AgentType.WEATHER: make_score(AgentType.WEATHER, 60.0),
            AgentType.SUPPLY: make_score(AgentType.SUPPLY, 40.0),
        }
        view = engine.compute(consensus_type="MARKET_DIRECTION", target="STORAGE_BCF", forecasts=forecasts, scores=scores)
        assert sum(w.weight for w in view.agent_weights) == pytest.approx(1.0, abs=1e-3)


class TestAgreementLabel:
    def test_unanimous_direction_is_high_agreement(self, engine):
        forecasts = [
            make_forecast(AgentType.STORAGE, SignalDirection.BULLISH),
            make_forecast(AgentType.WEATHER, SignalDirection.BULLISH),
        ]
        view = engine.compute(consensus_type="MARKET_DIRECTION", target="STORAGE_BCF", forecasts=forecasts, scores={})
        assert view.agreement_label == "HIGH"
        assert view.dissenting_agents == []

    def test_evenly_split_direction_is_low_agreement(self, engine):
        forecasts = [
            make_forecast(AgentType.STORAGE, SignalDirection.BULLISH, confidence=0.5),
            make_forecast(AgentType.WEATHER, SignalDirection.BEARISH, confidence=0.5),
            make_forecast(AgentType.SUPPLY, SignalDirection.NEUTRAL, confidence=0.5),
        ]
        scores = {t: make_score(t, 50.0) for t in (AgentType.STORAGE, AgentType.WEATHER, AgentType.SUPPLY)}
        view = engine.compute(consensus_type="MARKET_DIRECTION", target="STORAGE_BCF", forecasts=forecasts, scores=scores)
        assert view.agreement_label == "LOW"
        assert len(view.dissenting_agents) == 2


class TestConsensusValue:
    def test_same_target_forecasts_get_a_weighted_value(self, engine):
        forecasts = [
            make_forecast(AgentType.STORAGE, SignalDirection.BULLISH, forecast_value=-90.0, confidence=1.0),
        ]
        view = engine.compute(consensus_type="STORAGE_FORECAST", target="STORAGE_BCF", forecasts=forecasts, scores={})
        assert view.consensus_value == pytest.approx(-90.0)

    def test_mixed_targets_never_produce_a_fabricated_scalar(self, engine):
        """Averaging a price forecast with a production-trend forecast would be
        meaningless -- consensus_value must stay None when targets differ."""
        forecasts = [
            make_forecast(AgentType.STORAGE, SignalDirection.BULLISH, target="STORAGE_BCF"),
            make_forecast(AgentType.SUPPLY, SignalDirection.BEARISH, target="PRODUCTION_BCF_D", forecast_value=1.0),
        ]
        view = engine.compute(consensus_type="MARKET_DIRECTION", target="STORAGE_BCF", forecasts=forecasts, scores={})
        assert view.consensus_value is None

    def test_variance_vs_market_is_computed_when_both_present(self, engine):
        forecasts = [make_forecast(AgentType.STORAGE, SignalDirection.BULLISH, forecast_value=88.0, confidence=1.0)]
        view = engine.compute(
            consensus_type="STORAGE_FORECAST",
            target="STORAGE_BCF",
            forecasts=forecasts,
            scores={},
            market_consensus_value=86.0,
        )
        assert view.consensus_value == pytest.approx(88.0)
        assert view.market_consensus_value == pytest.approx(86.0)
        assert view.variance_vs_market == pytest.approx(2.0)

    def test_variance_vs_market_is_none_without_market_value(self, engine):
        forecasts = [make_forecast(AgentType.STORAGE, SignalDirection.BULLISH, forecast_value=88.0)]
        view = engine.compute(consensus_type="STORAGE_FORECAST", target="STORAGE_BCF", forecasts=forecasts, scores={})
        assert view.variance_vs_market is None


class TestDrivers:
    def test_drivers_are_deduplicated_across_forecasts(self, engine):
        forecasts = [
            make_forecast(AgentType.STORAGE, SignalDirection.BULLISH, drivers=["cold snap", "low injections"]),
            make_forecast(AgentType.WEATHER, SignalDirection.BULLISH, drivers=["cold snap"]),
        ]
        view = engine.compute(consensus_type="MARKET_DIRECTION", target="STORAGE_BCF", forecasts=forecasts, scores={})
        assert view.drivers.count("cold snap") == 1
        assert "low injections" in view.drivers


def test_agent_count_matches_forecast_count(engine):
    forecasts = [
        make_forecast(AgentType.STORAGE, SignalDirection.BULLISH),
        make_forecast(AgentType.WEATHER, SignalDirection.BEARISH),
    ]
    view = engine.compute(consensus_type="MARKET_DIRECTION", target="STORAGE_BCF", forecasts=forecasts, scores={})
    assert view.agent_count == 2
