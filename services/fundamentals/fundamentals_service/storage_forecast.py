"""Weekly EIA storage report forecasting engine.

Turns a set of daily balance estimates into a `StorageForecast` matching the weekly
EIA Natural Gas Storage Report cadence (Thursday release, week ending the prior
Friday).
"""

from __future__ import annotations

from datetime import date, timedelta

from schemas import GasBalanceDaily, StorageForecast

from .balance import summarize_period

BCF_PER_DAY_UNCERTAINTY = 3.0  # +/- range widens with forecast horizon


def forecast_storage_week(
    *,
    week_ending: date,
    daily_balances: list[GasBalanceDaily],
    five_year_average_bcf: float,
    last_year_bcf: float,
    market_consensus_bcf: float | None = None,
    drivers: list[str] | None = None,
    regional_breakdown: dict[str, float] | None = None,
) -> StorageForecast:
    """`daily_balances` should cover the EIA storage week (7 days ending `week_ending`,
    typically a Friday). The forecast is the (rounded) net implied storage flow for
    the period; the range widens with the number of days whose balance is itself a
    forecast (rather than an already-observed actual) — approximated here via a fixed
    per-day uncertainty since we do not yet distinguish nowcast vs. forecast days at
    this layer.
    """
    summary = summarize_period(daily_balances)
    forecast_bcf = round(summary["balance_bcf"])
    uncertainty = BCF_PER_DAY_UNCERTAINTY * max(1, summary["days"]) ** 0.5

    confidence = 0.75 if summary["days"] >= 5 else 0.5

    return StorageForecast(
        week_ending=week_ending,
        forecast_bcf=forecast_bcf,
        market_consensus_bcf=market_consensus_bcf,
        five_year_average_bcf=five_year_average_bcf,
        last_year_bcf=last_year_bcf,
        forecast_range_low=round(forecast_bcf - uncertainty),
        forecast_range_high=round(forecast_bcf + uncertainty),
        confidence=confidence,
        drivers=drivers or [],
        regional_breakdown=regional_breakdown or {},
    )


def project_end_of_season(
    *,
    current_inventory_bcf: float,
    weekly_forecasts_bcf: list[float],
) -> float:
    """Sum a sequence of weekly net-flow forecasts (bcf, signed) onto current
    inventory to project the end-of-season (end of injection or withdrawal season)
    storage level."""
    return current_inventory_bcf + sum(weekly_forecasts_bcf)


def week_ending_for(as_of: date) -> date:
    """EIA storage weeks end on Friday; the report covering that week is released the
    following Thursday."""
    days_since_friday = (as_of.weekday() - 4) % 7
    return as_of - timedelta(days=days_since_friday)
