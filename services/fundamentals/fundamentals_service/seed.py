"""Deterministic SIMULATED seed data so every fundamentals panel is demoable with
zero paid subscriptions. All values are clearly synthetic (seasonal shape + small
deterministic noise) and are always labeled SIMULATED by the API layer.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

from schemas import GasBalanceDaily

from .lng import LNGTerminalState
from .power_burn import PowerMarketState

SEED_RNG_KEY = "alphagasiq-seed-v1"


def generate_daily_balances(*, end_date: date, num_days: int = 120) -> list[GasBalanceDaily]:
    rng = random.Random(SEED_RNG_KEY)
    balances: list[GasBalanceDaily] = []
    for i in range(num_days, 0, -1):
        d = end_date - timedelta(days=i)
        doy = d.timetuple().tm_yday
        seasonal_heat = max(0.0, math.cos((doy - 15) / 365 * 2 * math.pi))  # winter peak
        seasonal_cool = max(0.0, -math.cos((doy - 15) / 365 * 2 * math.pi))  # summer peak

        production = 104.0 + rng.uniform(-1.0, 1.0) + 0.5 * math.sin(doy / 30)
        canadian_imports = 6.0 + rng.uniform(-0.5, 0.5)
        lng_sendout = 0.2 + rng.uniform(-0.05, 0.05)
        other_supply = 1.0

        rescom = 15.0 + 45.0 * seasonal_heat + rng.uniform(-1.5, 1.5)
        industrial = 22.0 + rng.uniform(-1.0, 1.0)
        power_burn = 28.0 + 14.0 * seasonal_cool + rng.uniform(-1.5, 1.5)
        lng_feedgas = 14.5 + rng.uniform(-0.4, 0.4)
        mexico_exports = 6.5 + rng.uniform(-0.3, 0.3)
        other_exports = 2.0

        balances.append(
            GasBalanceDaily(
                flow_date=d,
                production_bcf=round(production, 2),
                canadian_imports_bcf=round(canadian_imports, 2),
                lng_sendout_bcf=round(lng_sendout, 2),
                other_supply_bcf=round(other_supply, 2),
                rescom_demand_bcf=round(rescom, 2),
                industrial_demand_bcf=round(industrial, 2),
                power_burn_bcf=round(power_burn, 2),
                lng_feedgas_bcf=round(lng_feedgas, 2),
                mexico_exports_bcf=round(mexico_exports, 2),
                other_exports_bcf=round(other_exports, 2),
            )
        )
    return balances


def seed_storage_baseline(*, as_of: date) -> dict[str, float]:
    doy = as_of.timetuple().tm_yday
    seasonal = 1800 + 1600 * math.cos((doy - 260) / 365 * 2 * math.pi)  # peak ~Nov, trough ~Apr
    return {
        "current_inventory_bcf": round(seasonal, 0),
        "year_ago_inventory_bcf": round(seasonal * 0.97, 0),
        "five_year_average_bcf": round(seasonal * 1.0, 0),
        "five_year_low_bcf": round(seasonal * 0.85, 0),
        "five_year_high_bcf": round(seasonal * 1.15, 0),
    }


def seed_lng_terminals() -> list[LNGTerminalState]:
    return [
        LNGTerminalState("Sabine Pass", "Cameron Parish, LA", 4.9, 4.55),
        LNGTerminalState("Corpus Christi", "Corpus Christi, TX", 2.4, 2.15),
        LNGTerminalState("Freeport", "Freeport, TX", 2.14, 1.4, maintenance_status="PARTIAL_CURTAILMENT"),
        LNGTerminalState("Cameron", "Hackberry, LA", 2.0, 1.85),
        LNGTerminalState("Calcasieu Pass", "Cameron Parish, LA", 1.5, 1.3),
        LNGTerminalState("Plaquemines", "Plaquemines Parish, LA", 1.9, 1.1),
    ]


def seed_power_markets() -> list[PowerMarketState]:
    return [
        PowerMarketState("ERCOT", 55.0, 26.0, 4.0, 5.0, 12.0, 6.0, 1.5),
        PowerMarketState("PJM", 90.0, 32.0, 18.0, 15.0, 4.0, 2.0, 5.0),
        PowerMarketState("MISO", 70.0, 20.0, 22.0, 10.0, 8.0, 1.0, 6.0),
        PowerMarketState("CAISO", 32.0, 8.0, 0.0, 2.0, 3.0, 12.0, 4.0),
    ]
