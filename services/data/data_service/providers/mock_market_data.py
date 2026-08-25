from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from data_sdk import BaseDataProvider, FetchRequest, ProviderHealth
from schemas import DataClassification, Lineage, ObservationDraft

HENRY_HUB_SYMBOL = "NG"


def _contract_month_code(offset_months: int, as_of: datetime) -> str:
    month_codes = "FGHJKMNQUVXZ"  # NYMEX month letter codes, Jan..Dec
    total = as_of.month - 1 + offset_months
    year = as_of.year + total // 12
    month = total % 12
    return f"{HENRY_HUB_SYMBOL}{month_codes[month]}{str(year)[-2:]}"


class MockCMEProvider(BaseDataProvider):
    """Simulated Henry Hub Natural Gas futures curve (NYMEX/CME), M1-M36.

    Stands in for a properly-entitled CME Market Data API connection. Generates a
    plausible seasonal curve (winter premium) with small deterministic-per-day noise so
    the dashboard is fully demoable with zero market data subscription. Every value is
    tagged `SIMULATED` and clearly labeled as such wherever it reaches the UI.
    """

    provider_id = "mock_cme"
    classification = DataClassification.SIMULATED
    freshness_sla_seconds = 60

    def __init__(self, base_price: float = 2.85, seed: int | None = None):
        self.base_price = base_price
        self._seed = seed

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(provider_id=self.provider_id, status="healthy")

    async def fetch(self, request: FetchRequest) -> list[ObservationDraft]:
        as_of = request.end or datetime.now(timezone.utc)
        n_contracts = int(request.extra.get("n_contracts", 36))
        return self.normalize({"as_of": as_of, "n_contracts": n_contracts})

    def normalize(self, raw: Any) -> list[ObservationDraft]:
        as_of: datetime = raw["as_of"]
        n_contracts: int = raw["n_contracts"]
        rng = random.Random(self._seed if self._seed is not None else as_of.strftime("%Y-%m-%d"))
        drafts: list[ObservationDraft] = []
        for m in range(1, n_contracts + 1):
            month = (as_of.month - 1 + (m - 1)) % 12 + 1
            seasonal = 0.35 * math.cos((month - 1) / 12 * 2 * math.pi)  # winter premium
            term_structure = -0.01 * math.log(m)  # mild backwardation with tenor
            noise = rng.uniform(-0.03, 0.03)
            price = round(max(0.5, self.base_price + seasonal + term_structure + noise), 3)
            symbol = _contract_month_code(m - 1, as_of)
            drafts.append(
                ObservationDraft(
                    source="MOCK_CME",
                    source_type=self.classification,
                    series_id=f"NG.FUT.M{m}",
                    symbol=symbol,
                    commodity="NATURAL_GAS",
                    category="PRICE",
                    sub_category="FUTURES_SETTLEMENT",
                    geography="US",
                    location="HENRY_HUB",
                    value=price,
                    unit="USD_MMBTU",
                    observation_time=as_of,
                    publication_time=as_of,
                    metadata={"contract_month_offset": m, "curve_position": f"M{m}"},
                    lineage=Lineage(transform="MockCMEProvider.normalize"),
                )
            )
        return drafts


class MockICEProvider(BaseDataProvider):
    """Simulated ICE data (e.g. TTF, basis) — stands in for a licensed ICE connection."""

    provider_id = "mock_ice"
    classification = DataClassification.SIMULATED
    freshness_sla_seconds = 60

    def __init__(self, ttf_base_price: float = 9.50, seed: int | None = None):
        self.ttf_base_price = ttf_base_price
        self._seed = seed

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(provider_id=self.provider_id, status="healthy")

    async def fetch(self, request: FetchRequest) -> list[ObservationDraft]:
        as_of = request.end or datetime.now(timezone.utc)
        return self.normalize({"as_of": as_of})

    def normalize(self, raw: Any) -> list[ObservationDraft]:
        as_of: datetime = raw["as_of"]
        rng = random.Random(self._seed if self._seed is not None else as_of.strftime("%Y-%m-%d"))
        price = round(self.ttf_base_price + rng.uniform(-0.4, 0.4), 3)
        return [
            ObservationDraft(
                source="MOCK_ICE",
                source_type=self.classification,
                series_id="TTF.FRONT_MONTH",
                symbol="TTF",
                commodity="NATURAL_GAS",
                category="PRICE",
                sub_category="FUTURES_SETTLEMENT",
                geography="EU",
                location="TTF",
                value=price,
                unit="USD_MMBTU",
                observation_time=as_of,
                publication_time=as_of,
                lineage=Lineage(transform="MockICEProvider.normalize"),
            )
        ]
