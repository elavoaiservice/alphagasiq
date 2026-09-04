"""Regime detection engine (docs/architecture.md REGIME ENGINE).

Deterministic heuristics over already-computed fundamental signals — no LLM call, no
hidden state. Priority order: an identifiable shock (weather/supply/storage/LNG/
pipeline/news-driven) always wins over a plain volatility read, since "the market is
volatile because of X" is more useful to a trading desk than "the market is volatile."
Falls back to a volatility-only classification (NORMAL/LOW_VOLATILITY/HIGH_VOLATILITY)
when nothing more specific is detected.
"""

from __future__ import annotations

import statistics

from schemas import NewsEvent, Regime, RegimeResult, StorageForecast, WeatherDemandImpact

LOW_VOLATILITY_THRESHOLD = 0.01
HIGH_VOLATILITY_THRESHOLD = 0.035
WEATHER_SHOCK_BCF_THRESHOLD = 3.0
STORAGE_STRESS_SIGMA = 1.0  # multiples of (five_year_high - five_year_low)/2 beyond the range midpoint

_SUPPLY_EVENT_TYPES = {"hurricane", "freeze_off", "production_disruption", "producer_announcement"}
_PIPELINE_EVENT_TYPES = {"pipeline_notice", "maintenance"}
_GEOPOLITICAL_EVENT_TYPES = {"geopolitical_event", "shipping_disruption"}
_HIGH_MAGNITUDE_NEWS_THRESHOLD = 0.3


def realized_volatility(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    return statistics.pstdev(returns)


def detect_regime(
    *,
    recent_returns: list[float],
    weather_impact: WeatherDemandImpact | None = None,
    storage_forecast: StorageForecast | None = None,
    news_events: list[NewsEvent] | None = None,
) -> RegimeResult:
    vol = realized_volatility(recent_returns)
    news_events = news_events or []

    for event in sorted(news_events, key=lambda e: e.magnitude, reverse=True):
        if event.magnitude < _HIGH_MAGNITUDE_NEWS_THRESHOLD:
            continue
        if event.event_type in _SUPPLY_EVENT_TYPES:
            return _result(Regime.SUPPLY_SHOCK, event.magnitude, [f"News: {event.headline}"], vol)
        if event.event_type == "lng_outage":
            return _result(Regime.LNG_SHOCK, event.magnitude, [f"News: {event.headline}"], vol)
        if event.event_type in _PIPELINE_EVENT_TYPES:
            return _result(Regime.PIPELINE_CONSTRAINT, event.magnitude, [f"News: {event.headline}"], vol)
        if event.event_type in _GEOPOLITICAL_EVENT_TYPES:
            return _result(Regime.GEOPOLITICAL_SHOCK, event.magnitude, [f"News: {event.headline}"], vol)

    if weather_impact is not None and abs(weather_impact.total_demand_delta_bcf) >= WEATHER_SHOCK_BCF_THRESHOLD:
        return _result(
            Regime.WEATHER_SHOCK,
            weather_impact.confidence,
            [f"{weather_impact.model} implies {weather_impact.total_demand_delta_bcf:+.2f} Bcf/d demand shift"],
            vol,
        )

    if storage_forecast is not None:
        band_half_width = (storage_forecast.five_year_average_bcf and (
            (storage_forecast.forecast_range_high - storage_forecast.forecast_range_low) / 2
        )) or 1.0
        if storage_forecast.market_consensus_bcf is not None:
            surprise = abs(storage_forecast.forecast_bcf - storage_forecast.market_consensus_bcf)
            if band_half_width > 0 and surprise / band_half_width >= STORAGE_STRESS_SIGMA:
                return _result(
                    Regime.STORAGE_STRESS,
                    storage_forecast.confidence,
                    [f"Storage forecast diverges {surprise:.0f} Bcf from consensus"],
                    vol,
                )

    if vol >= HIGH_VOLATILITY_THRESHOLD:
        return _result(Regime.HIGH_VOLATILITY, 0.7, [f"Realized volatility {vol:.4f} exceeds threshold"], vol)
    if vol <= LOW_VOLATILITY_THRESHOLD and recent_returns:
        return _result(Regime.LOW_VOLATILITY, 0.6, [f"Realized volatility {vol:.4f} below threshold"], vol)

    return _result(Regime.NORMAL, 0.5, ["No shock or abnormal volatility detected"], vol)


def _result(regime: Regime, confidence: float, drivers: list[str], vol: float) -> RegimeResult:
    return RegimeResult(regime=regime, confidence=round(confidence, 3), drivers=drivers, realized_volatility=round(vol, 6))
