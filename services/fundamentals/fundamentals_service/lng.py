"""LNG economics: Henry Hub -> liquefaction -> shipping -> regasification netback vs.
TTF / JKM.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LNGTerminalState:
    name: str
    location: str
    capacity_bcf_d: float
    feedgas_bcf_d: float
    maintenance_status: str = "NORMAL"
    outage_status: str = "NONE"
    estimated_cargo_loadings: int = 0

    @property
    def utilization(self) -> float:
        if self.capacity_bcf_d <= 0:
            return 0.0
        return round(self.feedgas_bcf_d / self.capacity_bcf_d, 4)


@dataclass(frozen=True)
class NetbackResult:
    destination: str  # "TTF" | "JKM"
    henry_hub_price: float
    destination_price: float
    liquefaction_cost: float
    shipping_cost: float
    regasification_cost: float
    netback_usd_mmbtu: float
    export_incentivized: bool


def compute_netback(
    *,
    destination: str,
    henry_hub_price: float,
    destination_price: float,
    liquefaction_cost: float = 2.50,
    shipping_cost: float = 1.00,
    regasification_cost: float = 0.30,
) -> NetbackResult:
    """Netback = what a molecule delivered to `destination` is worth once shipped back
    to Henry Hub, net of the cost chain. A positive netback (destination price exceeds
    HH + full cost chain) signals an economic incentive to export."""
    total_cost = liquefaction_cost + shipping_cost + regasification_cost
    netback = destination_price - total_cost - henry_hub_price
    return NetbackResult(
        destination=destination,
        henry_hub_price=henry_hub_price,
        destination_price=destination_price,
        liquefaction_cost=liquefaction_cost,
        shipping_cost=shipping_cost,
        regasification_cost=regasification_cost,
        netback_usd_mmbtu=round(netback, 3),
        export_incentivized=netback > 0,
    )
