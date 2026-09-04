"""Phase 1 free-data-feed integration, Round 2 (spec section 26): a transparent,
reproducible Market Bias indicator built from weighted, cited components -- never
an LLM's judgment call. Pure and deterministic: same inputs always produce the same
score and the same driver breakdown, so a trader can always answer "why does it say
that" by reading the `drivers` list, not by re-asking an agent.

Each driver function returns `None` when its required inputs are missing (not a
zero-filled fake contribution) -- a driver absent from the result means "no data to
judge this by," not "neutral." If every driver comes back `None`, the whole result is
`MarketBiasLabel.INSUFFICIENT_DATA` rather than a fabricated 50/neutral guess.

Deliberately omits a "Pipeline constraints" driver the original spec lists alongside
these: this codebase has no real pipeline-constraint data source (FERC eLibrary and
per-pipeline EBB sites stay honest `NotImplementedProvider` stubs, `services/data/
data_service/providers/stubs.py`) -- a placeholder driver that's always zero would
imply coverage that doesn't exist, which is worse than omitting it and saying why.
"""

from __future__ import annotations

from datetime import datetime, timezone

from schemas import GasBalanceDaily, MarketBiasDriver, MarketBiasLabel, MarketBiasResult

_BASELINE_SCORE = 50.0
_TREND_WINDOW_DAYS = 7  # "recent week" vs "prior week" for the balance-derived drivers


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _label_for_score(score: float) -> MarketBiasLabel:
    if score >= 80:
        return MarketBiasLabel.STRONGLY_BULLISH
    if score >= 60:
        return MarketBiasLabel.BULLISH
    if score >= 40:
        return MarketBiasLabel.NEUTRAL
    if score >= 20:
        return MarketBiasLabel.BEARISH
    return MarketBiasLabel.STRONGLY_BEARISH


def _weather_driver(weather_kwargs: dict | None) -> MarketBiasDriver | None:
    if not weather_kwargs:
        return None
    required = ("hdd_run", "hdd_comparison", "cdd_run", "cdd_comparison")
    if any(weather_kwargs.get(k) is None for k in required):
        return None
    hdd_delta = weather_kwargs["hdd_run"] - weather_kwargs["hdd_comparison"]
    cdd_delta = weather_kwargs["cdd_run"] - weather_kwargs["cdd_comparison"]
    # Colder-than-prior (higher HDD) and hotter-than-prior (higher CDD) both mean
    # more gas demand (heating and power-burn-for-cooling, respectively) -> bullish.
    points = _clamp(hdd_delta * 2.0 + cdd_delta * 1.5, -20.0, 20.0)
    return MarketBiasDriver(
        name="Weather",
        points=round(points, 1),
        rationale=f"HDD delta {hdd_delta:+.1f}, CDD delta {cdd_delta:+.1f} vs. the prior run",
    )


def _storage_driver(storage_baseline: dict | None) -> MarketBiasDriver | None:
    if not storage_baseline:
        return None
    current = storage_baseline.get("current_inventory_bcf")
    average = storage_baseline.get("five_year_average_bcf")
    if current is None or average is None:
        return None
    deficit = average - current  # positive = below the 5-year average = bullish
    points = _clamp(deficit / 10.0, -20.0, 20.0)
    direction = "deficit vs." if deficit >= 0 else "surplus vs."
    return MarketBiasDriver(
        name="Storage",
        points=round(points, 1),
        rationale=f"{abs(deficit):.0f} Bcf {direction} the 5-year average",
    )


def _balance_trend(balances: list[GasBalanceDaily], field: str) -> float | None:
    """Recent-week average minus prior-week average for one `GasBalanceDaily` field
    -- `None` when there isn't enough history (fewer than 2 full weeks) to compute a
    trend rather than a single noisy day-over-day blip."""
    if len(balances) < _TREND_WINDOW_DAYS * 2:
        return None
    ordered = sorted(balances, key=lambda b: b.flow_date)
    recent_week = ordered[-_TREND_WINDOW_DAYS:]
    prior_week = ordered[-_TREND_WINDOW_DAYS * 2 : -_TREND_WINDOW_DAYS]
    recent_avg = sum(getattr(b, field) for b in recent_week) / len(recent_week)
    prior_avg = sum(getattr(b, field) for b in prior_week) / len(prior_week)
    return recent_avg - prior_avg


def _production_driver(balances: list[GasBalanceDaily] | None) -> MarketBiasDriver | None:
    if not balances:
        return None
    delta = _balance_trend(balances, "production_bcf")
    if delta is None:
        return None
    # More production = more supply = bearish.
    points = _clamp(-delta * 3.0, -15.0, 15.0)
    return MarketBiasDriver(
        name="Production", points=round(points, 1), rationale=f"Production {delta:+.2f} Bcf/d week-over-week"
    )


def _demand_driver(balances: list[GasBalanceDaily] | None) -> MarketBiasDriver | None:
    if not balances:
        return None
    ordered = sorted(balances, key=lambda b: b.flow_date)
    if len(ordered) < _TREND_WINDOW_DAYS * 2:
        return None
    recent_week = ordered[-_TREND_WINDOW_DAYS:]
    prior_week = ordered[-_TREND_WINDOW_DAYS * 2 : -_TREND_WINDOW_DAYS]

    def _rescom_industrial(b: GasBalanceDaily) -> float:
        return b.rescom_demand_bcf + b.industrial_demand_bcf

    recent_avg = sum(_rescom_industrial(b) for b in recent_week) / len(recent_week)
    prior_avg = sum(_rescom_industrial(b) for b in prior_week) / len(prior_week)
    delta = recent_avg - prior_avg
    points = _clamp(delta * 1.5, -15.0, 15.0)
    return MarketBiasDriver(
        name="Demand", points=round(points, 1), rationale=f"Res/comm + industrial demand {delta:+.2f} Bcf/d week-over-week"
    )


def _lng_driver(balances: list[GasBalanceDaily] | None) -> MarketBiasDriver | None:
    if not balances:
        return None
    delta = _balance_trend(balances, "lng_feedgas_bcf")
    if delta is None:
        return None
    points = _clamp(delta * 3.0, -10.0, 10.0)
    return MarketBiasDriver(
        name="LNG", points=round(points, 1), rationale=f"LNG feedgas {delta:+.2f} Bcf/d week-over-week"
    )


def _power_driver(balances: list[GasBalanceDaily] | None) -> MarketBiasDriver | None:
    if not balances:
        return None
    delta = _balance_trend(balances, "power_burn_bcf")
    if delta is None:
        return None
    points = _clamp(delta * 2.0, -10.0, 10.0)
    return MarketBiasDriver(
        name="Power", points=round(points, 1), rationale=f"Power burn {delta:+.2f} Bcf/d week-over-week"
    )


def _price_momentum_driver(recent_prices: list[float] | None) -> MarketBiasDriver | None:
    if not recent_prices or len(recent_prices) < 2 or recent_prices[0] == 0:
        return None
    pct_change = (recent_prices[-1] - recent_prices[0]) / recent_prices[0]
    points = _clamp(pct_change * 100 * 0.5, -10.0, 10.0)
    return MarketBiasDriver(
        name="Price/market", points=round(points, 1), rationale=f"M1 price {pct_change * 100:+.1f}% over the window"
    )


def _consensus_driver(bull_probability: float | None, bear_probability: float | None, confidence: float | None) -> MarketBiasDriver | None:
    if bull_probability is None or bear_probability is None or confidence is None:
        return None
    net = (bull_probability - bear_probability) * confidence
    points = _clamp(net * 15.0, -15.0, 15.0)
    return MarketBiasDriver(
        name="Agent consensus",
        points=round(points, 1),
        rationale=f"AlphaConsensus net bull-bear probability {net:+.2f} (confidence {confidence:.0%})",
    )


def compute_market_bias(
    *,
    weather_kwargs: dict | None = None,
    storage_baseline: dict | None = None,
    recent_balances: list[GasBalanceDaily] | None = None,
    recent_prices: list[float] | None = None,
    consensus_bull_probability: float | None = None,
    consensus_bear_probability: float | None = None,
    consensus_confidence: float | None = None,
    now: datetime | None = None,
) -> MarketBiasResult:
    drivers = [
        d
        for d in (
            _weather_driver(weather_kwargs),
            _storage_driver(storage_baseline),
            _production_driver(recent_balances),
            _demand_driver(recent_balances),
            _lng_driver(recent_balances),
            _power_driver(recent_balances),
            _price_momentum_driver(recent_prices),
            _consensus_driver(consensus_bull_probability, consensus_bear_probability, consensus_confidence),
        )
        if d is not None
    ]

    computed_at = now or datetime.now(timezone.utc)
    if not drivers:
        return MarketBiasResult(label=MarketBiasLabel.INSUFFICIENT_DATA, score=None, drivers=[], computed_at=computed_at)

    score = _clamp(_BASELINE_SCORE + sum(d.points for d in drivers), 0.0, 100.0)
    return MarketBiasResult(label=_label_for_score(score), score=round(score, 1), drivers=drivers, computed_at=computed_at)
