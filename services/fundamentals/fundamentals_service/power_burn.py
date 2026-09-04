"""Power-burn engine: estimate gas-fired generation demand from ISO/RTO load and
generation-mix data.
"""

from __future__ import annotations

from dataclasses import dataclass

MMBTU_PER_MWH_AT_HEAT_RATE_10 = 10.0  # MMBtu/MWh at a 10,000 Btu/kWh heat rate
BCF_PER_MMBTU = 1e-6 * 1000  # 1,000 MMBtu = 1 Mcf -> Bcf conversion handled below


@dataclass(frozen=True)
class PowerMarketState:
    iso: str
    load_gw: float
    gas_generation_gw: float
    coal_generation_gw: float
    nuclear_generation_gw: float
    wind_generation_gw: float
    solar_generation_gw: float
    hydro_generation_gw: float
    average_gas_heat_rate: float = 8.0  # thousand Btu per kWh (typical CCGT ~7-8)


def estimate_power_burn_bcf_d(state: PowerMarketState) -> float:
    """gas_generation_gw * 24h -> MWh, times heat rate (MMBtu/MWh) -> MMBtu/day,
    converted to Bcf/day (1 Bcf ~= 1,000,000 MMBtu at ~1,030 Btu/scf; we use the
    standard 1 MMBtu ~= 1 Mcf approximation used across the industry for burn
    estimates)."""
    mwh_per_day = state.gas_generation_gw * 1000 * 24
    mmbtu_per_day = mwh_per_day * state.average_gas_heat_rate
    bcf_per_day = mmbtu_per_day / 1_000_000
    return round(bcf_per_day, 3)
