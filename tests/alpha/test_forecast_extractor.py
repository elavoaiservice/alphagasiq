"""tests/alpha/test_forecast_extractor.py -- AlphaConsensus(TM)'s ForecastExtractor:
turns already-computed AgentResult outputs into the common AgentForecast shape.
Table-driven per source agent, mirroring test_impact_engine.py's style."""

from __future__ import annotations

import pytest
from alpha_service.forecast_extractor import ForecastExtractor
from schemas import AgentResult, AgentStatus, AgentType, ForecastHorizon, SignalDirection


def make_result(agent_type: AgentType, outputs: dict, *, confidence: float = 0.7) -> AgentResult:
    return AgentResult(
        agent_id=f"{agent_type.value.lower()}-agent",
        agent_name=f"{agent_type.value.title()} Agent",
        agent_type=agent_type,
        version="1.0.0",
        status=AgentStatus.SUCCESS,
        outputs=outputs,
        confidence=confidence,
    )


@pytest.fixture
def extractor() -> ForecastExtractor:
    return ForecastExtractor()


class TestStorageExtraction:
    def test_tighter_than_consensus_is_bullish(self, extractor):
        result = make_result(AgentType.STORAGE, {"forecast_bcf": -90.0, "market_consensus_bcf": -55.0})
        forecasts = extractor.extract(storage_result=result)
        assert len(forecasts) == 1
        assert forecasts[0].direction == SignalDirection.BULLISH
        assert forecasts[0].forecast_type == "STORAGE_WEEKLY"

    def test_looser_than_consensus_is_bearish(self, extractor):
        result = make_result(AgentType.STORAGE, {"forecast_bcf": -20.0, "market_consensus_bcf": -55.0})
        forecasts = extractor.extract(storage_result=result)
        assert forecasts[0].direction == SignalDirection.BEARISH

    def test_missing_consensus_falls_back_to_explicit_parameter(self, extractor):
        """The Storage Agent's own raw outputs never carry market_consensus_bcf --
        it's merged in downstream by chief_trading_agent.py. The caller must be able
        to supply it explicitly so the comparison isn't silently unavailable."""
        result = make_result(AgentType.STORAGE, {"forecast_bcf": -90.0})
        forecasts = extractor.extract(storage_result=result, storage_market_consensus_bcf=-55.0)
        assert len(forecasts) == 1
        assert forecasts[0].direction == SignalDirection.BULLISH

    def test_outputs_value_takes_priority_over_explicit_parameter(self, extractor):
        result = make_result(AgentType.STORAGE, {"forecast_bcf": -90.0, "market_consensus_bcf": -55.0})
        forecasts = extractor.extract(storage_result=result, storage_market_consensus_bcf=-1000.0)
        assert forecasts[0].direction == SignalDirection.BULLISH

    def test_no_consensus_at_all_yields_no_forecast(self, extractor):
        result = make_result(AgentType.STORAGE, {"forecast_bcf": -90.0})
        assert extractor.extract(storage_result=result) == []

    def test_missing_outputs_yields_no_forecast(self, extractor):
        assert extractor.extract(storage_result=None) == []


class TestWeatherExtraction:
    def test_valid_price_direction_is_extracted(self, extractor):
        result = make_result(AgentType.WEATHER, {"price_direction": "BULLISH", "total_demand_delta_bcf": 3.0})
        forecasts = extractor.extract(weather_result=result)
        assert len(forecasts) == 1
        assert forecasts[0].direction == SignalDirection.BULLISH
        assert forecasts[0].forecast_type == "WEATHER_DEMAND_IMPACT"

    def test_invalid_price_direction_yields_no_forecast(self, extractor):
        result = make_result(AgentType.WEATHER, {"price_direction": "NOT_A_DIRECTION"})
        assert extractor.extract(weather_result=result) == []


class TestSupplyDemandExtraction:
    def test_rising_production_is_bearish(self, extractor):
        result = make_result(AgentType.SUPPLY, {"production_trend_bcf_d": 1.5})
        forecasts = extractor.extract(supply_result=result)
        assert forecasts[0].direction == SignalDirection.BEARISH
        assert forecasts[0].forecast_type == "PRODUCTION_TREND"

    def test_falling_production_is_bullish(self, extractor):
        result = make_result(AgentType.SUPPLY, {"production_trend_bcf_d": -1.5})
        forecasts = extractor.extract(supply_result=result)
        assert forecasts[0].direction == SignalDirection.BULLISH

    def test_rising_demand_is_bullish(self, extractor):
        result = make_result(AgentType.DEMAND, {"demand_trend_bcf_d": 2.0})
        forecasts = extractor.extract(demand_result=result)
        assert forecasts[0].direction == SignalDirection.BULLISH
        assert forecasts[0].forecast_type == "DEMAND_TREND"

    def test_falling_demand_is_bearish(self, extractor):
        result = make_result(AgentType.DEMAND, {"demand_trend_bcf_d": -2.0})
        forecasts = extractor.extract(demand_result=result)
        assert forecasts[0].direction == SignalDirection.BEARISH


class TestPriceForecastExtraction:
    def test_up_probability_above_half_is_bullish(self, extractor):
        result = make_result(
            AgentType.FORECASTING,
            {
                "instrument": "HENRY_HUB",
                "horizon": ForecastHorizon.SEVEN_DAY.value,
                "price_forecast": 3.2,
                "return_forecast": 0.05,
                "up_probability": 0.65,
                "down_probability": 0.35,
                "expected_volatility": 0.2,
                "confidence": 0.7,
            },
        )
        forecasts = extractor.extract(forecast_result=result)
        assert len(forecasts) == 1
        assert forecasts[0].direction == SignalDirection.BULLISH
        assert forecasts[0].forecast_type == "PRICE_FORECAST"
        assert forecasts[0].horizon == "7d"

    def test_up_probability_below_half_is_bearish(self, extractor):
        result = make_result(
            AgentType.FORECASTING,
            {
                "instrument": "HENRY_HUB",
                "horizon": ForecastHorizon.ONE_DAY.value,
                "price_forecast": 3.2,
                "return_forecast": -0.05,
                "up_probability": 0.35,
                "down_probability": 0.65,
                "expected_volatility": 0.2,
                "confidence": 0.7,
            },
        )
        forecasts = extractor.extract(forecast_result=result)
        assert forecasts[0].direction == SignalDirection.BEARISH

    def test_missing_price_forecast_output_yields_no_forecast(self, extractor):
        result = make_result(AgentType.FORECASTING, {})
        assert extractor.extract(forecast_result=result) == []


class TestRelativeValueExtraction:
    def test_cheap_is_bullish(self, extractor):
        result = make_result(AgentType.RELATIVE_VALUE, {"direction": "CHEAP", "mispricing": 0.3})
        forecasts = extractor.extract(relative_value_result=result)
        assert forecasts[0].direction == SignalDirection.BULLISH
        assert forecasts[0].forecast_type == "RELATIVE_VALUE"

    def test_rich_is_bearish(self, extractor):
        result = make_result(AgentType.RELATIVE_VALUE, {"direction": "RICH", "mispricing": -0.3})
        forecasts = extractor.extract(relative_value_result=result)
        assert forecasts[0].direction == SignalDirection.BEARISH

    def test_missing_direction_yields_no_forecast(self, extractor):
        result = make_result(AgentType.RELATIVE_VALUE, {"mispricing": 0.3})
        assert extractor.extract(relative_value_result=result) == []


def test_all_sources_together_yield_one_forecast_each(extractor):
    storage = make_result(AgentType.STORAGE, {"forecast_bcf": -90.0, "market_consensus_bcf": -55.0})
    weather = make_result(AgentType.WEATHER, {"price_direction": "BULLISH"})
    supply = make_result(AgentType.SUPPLY, {"production_trend_bcf_d": -1.0})
    demand = make_result(AgentType.DEMAND, {"demand_trend_bcf_d": 1.0})
    forecasts = extractor.extract(
        storage_result=storage, weather_result=weather, supply_result=supply, demand_result=demand
    )
    assert len(forecasts) == 4
    assert {f.agent_type for f in forecasts} == {
        AgentType.STORAGE,
        AgentType.WEATHER,
        AgentType.SUPPLY,
        AgentType.DEMAND,
    }


def test_no_sources_yields_empty_list(extractor):
    assert extractor.extract() == []
