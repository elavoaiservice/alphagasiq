"""Relative value engine (docs/architecture.md QUANTITATIVE PLATFORM "Relative Value
Agent"): cross-market and cross-contract mispricing signals.

Two signals for the MVP:
1. HH-TTF netback: reuses `fundamentals_service.lng.compute_netback` — a strongly
   positive/negative netback implies the LNG export-arbitrage trade is unusually
   attractive/unattractive relative to its normal cost-chain-covered range.
2. Calendar spread vs. cost-of-carry: a simple storage-cost-based fair-value check on
   the M1-M2 spread. Real desks calibrate the carry cost from actual storage/financing
   rates; this uses an illustrative constant (`MONTHLY_CARRY_COST_USD_MMBTU`) that
   should be replaced with a calibrated figure before this signal is relied upon
   beyond a demo.
"""

from __future__ import annotations

from fundamentals_service.lng import compute_netback
from schemas import RelativeValueSignal

NETBACK_SIGNIFICANCE_THRESHOLD = 0.5  # $/MMBtu
MONTHLY_CARRY_COST_USD_MMBTU = 0.08  # illustrative storage + financing cost per month
CALENDAR_SPREAD_SIGNIFICANCE_THRESHOLD = 0.05  # $/MMBtu


def hh_ttf_netback_signal(*, henry_hub_price: float, ttf_price: float) -> RelativeValueSignal:
    netback = compute_netback(destination="TTF", henry_hub_price=henry_hub_price, destination_price=ttf_price)
    mispricing = netback.netback_usd_mmbtu
    if mispricing > NETBACK_SIGNIFICANCE_THRESHOLD:
        direction = "CHEAP"  # HH cheap relative to TTF net of full cost chain -> export arb attractive
        rationale = "Henry Hub is cheap relative to TTF net of the full liquefaction/shipping/regas chain — export economics favorable."
    elif mispricing < -NETBACK_SIGNIFICANCE_THRESHOLD:
        direction = "RICH"
        rationale = "Henry Hub is rich relative to TTF net of the full cost chain — export economics unfavorable."
    else:
        direction = "FAIR"
        rationale = "Netback is within the normal range; no significant export-arbitrage signal."

    return RelativeValueSignal(
        pair="HH_TTF_NETBACK",
        signal_type="LNG_EXPORT_ARBITRAGE",
        fair_value_estimate=0.0,
        actual_value=round(mispricing, 4),
        mispricing=round(mispricing, 4),
        direction=direction,
        confidence=min(1.0, abs(mispricing) / (2 * NETBACK_SIGNIFICANCE_THRESHOLD)) if mispricing else 0.3,
        rationale=rationale,
    )


def calendar_spread_signal(*, m1_price: float, m2_price: float) -> RelativeValueSignal:
    actual_spread = m2_price - m1_price
    fair_spread = MONTHLY_CARRY_COST_USD_MMBTU
    mispricing = actual_spread - fair_spread

    if mispricing > CALENDAR_SPREAD_SIGNIFICANCE_THRESHOLD:
        direction = "RICH"  # M2 trading rich to M1 beyond cost-of-carry -> calendar spread (long M1/short M2) looks cheap
        rationale = "M1-M2 contango exceeds the illustrative cost-of-carry — the calendar spread looks statistically cheap to buy (long M1 / short M2)."
    elif mispricing < -CALENDAR_SPREAD_SIGNIFICANCE_THRESHOLD:
        direction = "CHEAP"
        rationale = "M1-M2 spread is narrower than (or inverted vs.) cost-of-carry — the calendar spread looks statistically rich (short M1 / long M2)."
    else:
        direction = "FAIR"
        rationale = "M1-M2 spread is consistent with the illustrative cost-of-carry; no significant signal."

    return RelativeValueSignal(
        pair="NG_M1_M2_CALENDAR_SPREAD",
        signal_type="COST_OF_CARRY",
        fair_value_estimate=round(fair_spread, 4),
        actual_value=round(actual_spread, 4),
        mispricing=round(mispricing, 4),
        direction=direction,
        confidence=min(1.0, abs(mispricing) / (2 * CALENDAR_SPREAD_SIGNIFICANCE_THRESHOLD)) if mispricing else 0.3,
        rationale=rationale,
    )
