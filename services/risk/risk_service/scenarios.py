"""Stress-testing scenario engine.

Applies a deterministic shock to current paper positions and the Henry Hub curve and
reports the resulting P&L / risk impact. No live capital is ever at risk — the
portfolio being stressed is always the paper-trading book.
"""

from __future__ import annotations

from dataclasses import dataclass

from .metrics import PositionSnapshot, gross_exposure, historical_var


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    name: str
    description: str
    price_shock_pct: float  # applied to Henry Hub price, e.g. +0.25 = +25%
    demand_shock_bcf_d: float = 0.0
    supply_shock_bcf_d: float = 0.0
    volatility_multiplier: float = 1.0


SCENARIOS: list[Scenario] = [
    Scenario("polar_vortex", "Polar Vortex", "Extreme cold across Midwest/Northeast", 0.30, demand_shock_bcf_d=8.0, volatility_multiplier=1.8),
    Scenario("weather_warm_15", "15% Warmer Weather", "Sustained warm anomaly vs. normal", -0.15, demand_shock_bcf_d=-5.0),
    Scenario("weather_cold_15", "15% Colder Weather", "Sustained cold anomaly vs. normal", 0.15, demand_shock_bcf_d=5.0),
    Scenario("major_hurricane", "Major Hurricane (Gulf Coast)", "Gulf production/LNG disruption", 0.20, supply_shock_bcf_d=-4.0, volatility_multiplier=2.0),
    Scenario("freeport_lng_outage", "Major LNG Terminal Shutdown", "Large LNG terminal fully offline", -0.18, demand_shock_bcf_d=-2.1),
    Scenario("production_outage_2bcf", "2 Bcf/d Production Outage", "Regional production disruption", 0.10, supply_shock_bcf_d=-2.0),
    Scenario("production_outage_5bcf", "5 Bcf/d Production Outage", "Major production disruption", 0.28, supply_shock_bcf_d=-5.0, volatility_multiplier=1.6),
    Scenario("record_production", "Record Production", "Production breaks to new highs", -0.12, supply_shock_bcf_d=3.0),
    Scenario("lng_feedgas_decline", "LNG Feedgas Decline", "Broad feedgas demand pullback", -0.08, demand_shock_bcf_d=-1.5),
    Scenario("pipeline_disruption", "Pipeline Disruption", "Major interstate pipeline outage", 0.12, supply_shock_bcf_d=-1.5),
    Scenario("storage_surprise_plus_20", "EIA Storage Surprise +20 Bcf", "Bearish surprise vs. consensus", -0.06),
    Scenario("storage_surprise_minus_20", "EIA Storage Surprise -20 Bcf", "Bullish surprise vs. consensus", 0.06),
    Scenario("ttf_collapse", "TTF Price Collapse", "European gas prices collapse, LNG diverts to Atlantic", -0.10, demand_shock_bcf_d=-1.0),
    Scenario("ttf_spike", "TTF Price Spike", "European gas prices spike, LNG pulled from US", 0.14, demand_shock_bcf_d=1.0),
]

_SCENARIO_BY_ID = {s.scenario_id: s for s in SCENARIOS}


@dataclass(frozen=True)
class ScenarioResult:
    scenario: Scenario
    portfolio_pnl: float
    strategy_pnl: dict[str, float]
    margin_impact: float
    var_impact: float
    largest_risk_contributor: str


def get_scenario(scenario_id: str) -> Scenario:
    return _SCENARIO_BY_ID[scenario_id]


def run_scenario(scenario: Scenario, positions: list[PositionSnapshot]) -> ScenarioResult:
    baseline_var = historical_var([p.unrealized_pnl / max(p.price, 1e-6) for p in positions])

    shocked_pnl = 0.0
    strategy_pnl: dict[str, float] = {}
    largest_contributor = ""
    largest_contribution = 0.0

    for p in positions:
        shocked_price = p.price * (1 + scenario.price_shock_pct)
        pnl_delta = (shocked_price - p.price) * p.quantity * p.delta
        shocked_pnl += pnl_delta
        strategy_pnl[p.instrument] = strategy_pnl.get(p.instrument, 0.0) + round(pnl_delta, 2)
        if abs(pnl_delta) > abs(largest_contribution):
            largest_contribution = pnl_delta
            largest_contributor = p.instrument

    shocked_var = baseline_var * scenario.volatility_multiplier
    margin_impact = gross_exposure(positions) * abs(scenario.price_shock_pct) * 0.1

    return ScenarioResult(
        scenario=scenario,
        portfolio_pnl=round(shocked_pnl, 2),
        strategy_pnl=strategy_pnl,
        margin_impact=round(margin_impact, 2),
        var_impact=round(shocked_var - baseline_var, 2),
        largest_risk_contributor=largest_contributor or "n/a",
    )
