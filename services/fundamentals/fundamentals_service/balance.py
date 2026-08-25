"""Lower-48 daily natural gas balance engine.

SUPPLY = dry gas production + Canadian imports + LNG sendout/imports + other supply
DEMAND = residential/commercial + industrial + power burn + LNG feedgas + Mexico
         exports + other pipeline exports
BALANCE = SUPPLY - DEMAND

A positive balance implies net supply surplus (storage injection pressure); negative
implies a supply deficit (storage withdrawal pressure). `GasBalanceDaily` (in
`packages/schemas`) carries the raw components and exposes `supply_total_bcf`,
`demand_total_bcf`, and `balance_bcf` as computed properties so this module stays a
thin, easily-testable set of pure functions.
"""

from __future__ import annotations

from schemas import GasBalanceDaily


def implied_storage_flow_bcf(balance: GasBalanceDaily) -> float:
    """The balance directly *is* the implied daily storage flow: a surplus fills
    storage, a deficit draws it down. Kept as a named function (rather than inlining
    `.balance_bcf`) so callers read intent, and so a future refinement (e.g. netting out
    unaccounted-for gas / pipeline linepack) has one place to change.
    """
    return balance.balance_bcf


def summarize_period(balances: list[GasBalanceDaily]) -> dict[str, float]:
    """Aggregate a list of daily balances (e.g. one EIA storage week, Fri-Thu) into
    period totals used by the storage forecasting engine."""
    if not balances:
        return {
            "supply_total_bcf": 0.0,
            "demand_total_bcf": 0.0,
            "balance_bcf": 0.0,
            "days": 0,
        }
    return {
        "supply_total_bcf": sum(b.supply_total_bcf for b in balances),
        "demand_total_bcf": sum(b.demand_total_bcf for b in balances),
        "balance_bcf": sum(b.balance_bcf for b in balances),
        "days": len(balances),
    }
