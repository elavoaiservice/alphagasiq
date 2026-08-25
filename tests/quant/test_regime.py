from quant_service.regime import detect_regime, realized_volatility
from schemas import NewsEvent, Regime, StorageForecast, WeatherDemandImpact
from datetime import datetime, timezone


def make_news(event_type: str, magnitude: float, headline: str = "test headline") -> NewsEvent:
    return NewsEvent(
        headline=headline,
        source="TEST",
        source_url="https://example.test",
        published_at=datetime.now(timezone.utc),
        event_type=event_type,
        summary=headline,
        bullish_bearish="NEUTRAL",
        magnitude=magnitude,
        confidence=0.7,
    )


def make_weather(total_delta: float) -> WeatherDemandImpact:
    return WeatherDemandImpact(
        model="ECMWF", run="00z", comparison_run="12z",
        hdd_delta=1.0, cdd_delta=0.0,
        estimated_rescom_delta_bcf=total_delta, estimated_power_burn_delta_bcf=0.0,
        total_demand_delta_bcf=total_delta, price_direction="BULLISH" if total_delta > 0 else "BEARISH",
        confidence=0.7,
    )


def make_storage(forecast_bcf: float, consensus_bcf: float) -> StorageForecast:
    return StorageForecast(
        week_ending=datetime.now(timezone.utc).date(),
        forecast_bcf=forecast_bcf,
        market_consensus_bcf=consensus_bcf,
        five_year_average_bcf=3000,
        last_year_bcf=2950,
        forecast_range_low=forecast_bcf - 5,
        forecast_range_high=forecast_bcf + 5,
        confidence=0.7,
    )


class TestRealizedVolatility:
    def test_zero_for_short_series(self):
        assert realized_volatility([0.01]) == 0.0

    def test_positive_for_varying_returns(self):
        assert realized_volatility([0.01, -0.02, 0.015, -0.01]) > 0


class TestDetectRegime:
    def test_normal_when_nothing_unusual(self):
        # stdev ~0.019 - between LOW_VOLATILITY_THRESHOLD (0.01) and
        # HIGH_VOLATILITY_THRESHOLD (0.035), i.e. deliberately unremarkable.
        result = detect_regime(recent_returns=[0.02, -0.015, 0.025, -0.02, 0.018])
        assert result.regime == Regime.NORMAL

    def test_high_volatility_detected(self):
        result = detect_regime(recent_returns=[0.08, -0.09, 0.07, -0.08, 0.09])
        assert result.regime == Regime.HIGH_VOLATILITY

    def test_low_volatility_detected(self):
        result = detect_regime(recent_returns=[0.001, -0.001, 0.0005, -0.0008])
        assert result.regime == Regime.LOW_VOLATILITY

    def test_weather_shock_overrides_plain_volatility_read(self):
        result = detect_regime(recent_returns=[0.001, -0.001], weather_impact=make_weather(5.0))
        assert result.regime == Regime.WEATHER_SHOCK

    def test_small_weather_delta_does_not_trigger_shock(self):
        result = detect_regime(recent_returns=[0.001, -0.001], weather_impact=make_weather(0.5))
        assert result.regime != Regime.WEATHER_SHOCK

    def test_storage_stress_on_large_consensus_divergence(self):
        result = detect_regime(
            recent_returns=[0.001, -0.001],
            storage_forecast=make_storage(forecast_bcf=50, consensus_bcf=90),
        )
        assert result.regime == Regime.STORAGE_STRESS

    def test_supply_shock_from_hurricane_news(self):
        result = detect_regime(
            recent_returns=[0.001, -0.001],
            news_events=[make_news("hurricane", 0.6)],
        )
        assert result.regime == Regime.SUPPLY_SHOCK

    def test_lng_shock_from_lng_outage_news(self):
        result = detect_regime(recent_returns=[0.001], news_events=[make_news("lng_outage", 0.5)])
        assert result.regime == Regime.LNG_SHOCK

    def test_pipeline_constraint_from_pipeline_notice_news(self):
        result = detect_regime(recent_returns=[0.001], news_events=[make_news("pipeline_notice", 0.4)])
        assert result.regime == Regime.PIPELINE_CONSTRAINT

    def test_geopolitical_shock_from_shipping_disruption_news(self):
        result = detect_regime(recent_returns=[0.001], news_events=[make_news("shipping_disruption", 0.45)])
        assert result.regime == Regime.GEOPOLITICAL_SHOCK

    def test_low_magnitude_news_does_not_trigger_shock(self):
        result = detect_regime(recent_returns=[0.001, -0.001], news_events=[make_news("hurricane", 0.1)])
        assert result.regime != Regime.SUPPLY_SHOCK

    def test_news_takes_priority_over_weather_and_storage(self):
        result = detect_regime(
            recent_returns=[0.001],
            weather_impact=make_weather(5.0),
            storage_forecast=make_storage(50, 90),
            news_events=[make_news("hurricane", 0.9)],
        )
        assert result.regime == Regime.SUPPLY_SHOCK

    def test_highest_magnitude_news_event_wins_among_multiple(self):
        result = detect_regime(
            recent_returns=[0.001],
            news_events=[make_news("pipeline_notice", 0.35), make_news("hurricane", 0.9)],
        )
        assert result.regime == Regime.SUPPLY_SHOCK

    def test_confidence_is_bounded(self):
        result = detect_regime(recent_returns=[0.001, -0.001])
        assert 0 <= result.confidence <= 1
