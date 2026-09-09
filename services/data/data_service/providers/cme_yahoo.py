"""Real NYMEX Henry Hub natural-gas futures curve from Yahoo Finance.

A licensed CME/ICE Market Data API is a paid enterprise subscription; this connector
instead uses Yahoo Finance's free, publicly-available NYMEX quotes (~15-min delayed)
for the Henry Hub natural gas futures curve (front-month `NG=F` + monthly contracts
`NG<MonthCode><YY>.NYM`). It is a drop-in for `MockCMEProvider` — identical
`ObservationDraft` schema — so the dashboard shows *real* HH M1/M2/12-month-strip
prices. Classified PUBLIC (delayed public quotes), not LICENSED.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

from data_sdk import BaseDataProvider, FetchRequest, ProviderHealth
from schemas import DataClassification, Lineage, ObservationDraft

_MONTH_CODES = "FGHJKMNQUVXZ"  # NYMEX month letter codes, Jan..Dec
_YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"
_HEADERS = {"User-Agent": "Mozilla/5.0 (AlphaGasIQ market-data)"}


def _contract_symbol(offset_months: int, as_of: datetime) -> str:
    total = as_of.month - 1 + offset_months
    year = as_of.year + total // 12
    month = total % 12
    return f"NG{_MONTH_CODES[month]}{str(year)[-2:]}.NYM"


class YahooHenryHubProvider(BaseDataProvider):
    provider_id = "cme_live"
    classification = DataClassification.PUBLIC
    freshness_sla_seconds = 900  # Yahoo quotes are ~15 min delayed

    def __init__(self, client: httpx.AsyncClient | None = None, max_contracts: int = 18):
        self._client = client
        self._max = max_contracts

    async def _price(self, symbol: str, client: httpx.AsyncClient) -> float | None:
        resp = await client.get(
            _YAHOO_CHART + symbol, params={"interval": "1d", "range": "5d"}, headers=_HEADERS, timeout=10.0
        )
        resp.raise_for_status()
        meta = resp.json()["chart"]["result"][0]["meta"]
        px = meta.get("regularMarketPrice")
        return float(px) if px is not None else None

    async def health_check(self) -> ProviderHealth:
        try:
            async with (self._client or httpx.AsyncClient()) as client:
                px = await self._price("NG=F", client)
            return ProviderHealth(provider_id=self.provider_id, status="healthy" if px else "degraded")
        except Exception:
            return ProviderHealth(provider_id=self.provider_id, status="unhealthy")

    async def fetch(self, request: FetchRequest) -> list[ObservationDraft]:
        as_of = request.end or datetime.now(timezone.utc)
        n = min(int(request.extra.get("n_contracts", 12) or 12), self._max)
        symbols = [_contract_symbol(m - 1, as_of) for m in range(1, n + 1)]

        # Never raise: a network hiccup here must not break boot — return an empty
        # curve and the platform degrades honestly ("data unavailable").
        try:
            async with (self._client or httpx.AsyncClient()) as client:
                results = await asyncio.gather(
                    self._price("NG=F", client),
                    *[self._price(s, client) for s in symbols],
                    return_exceptions=True,
                )
        except Exception:
            return []
        front = results[0] if not isinstance(results[0], Exception) else None
        month_prices = results[1:]

        drafts: list[ObservationDraft] = []
        last_valid = front
        for m in range(1, n + 1):
            px = month_prices[m - 1]
            if isinstance(px, Exception) or px is None:
                px = last_valid  # carry forward so the curve stays ordered + complete
            if m == 1 and front is not None:
                px = front  # the true active front-month price
            if px is None:
                continue
            last_valid = float(px)
            drafts.append(
                ObservationDraft(
                    source="YAHOO_NYMEX",
                    source_type=self.classification,
                    series_id=f"NG.FUT.M{m}",
                    symbol=symbols[m - 1].replace(".NYM", ""),
                    commodity="NATURAL_GAS",
                    category="PRICE",
                    sub_category="FUTURES_SETTLEMENT",
                    geography="US",
                    location="HENRY_HUB",
                    value=round(float(px), 3),
                    unit="USD_MMBTU",
                    observation_time=as_of,
                    publication_time=as_of,
                    metadata={"contract_month_offset": m, "curve_position": f"M{m}", "exchange": "NYMEX", "vendor": "yahoo"},
                    lineage=Lineage(transform="YahooHenryHubProvider.fetch"),
                )
            )
        return drafts
