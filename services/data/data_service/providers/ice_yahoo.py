"""Real ICE Dutch TTF natural-gas futures from Yahoo Finance, converted to USD/MMBtu.

The counterpart to `cme_yahoo.YahooHenryHubProvider`. A licensed ICE Market Data
subscription is a paid enterprise product; this connector uses Yahoo's free,
publicly-available quote for the Dutch TTF Natural Gas Calendar Month future
(`TTF=F`, ~15-min delayed).

**Why this connector needed more than a symbol swap.** TTF is quoted in
**EUR/MWh**; every consumer in this platform (the HH-TTF netback in
`quant_service.relative_value`, `fundamentals_service.lng.compute_netback`)
works in **USD/MMBtu**. Publishing a EUR/MWh number into a USD/MMBtu field
would silently corrupt the netback by a factor of ~3.4 (unit) times the FX rate
-- a relative-value signal that is confidently, invisibly wrong. So this
provider fetches the EUR/USD rate (`EURUSD=X`) in the same pass and converts:

    USD/MMBtu = (EUR/MWh x USD-per-EUR) / 3.412142 MMBtu-per-MWh

**If the FX leg fails, the whole fetch returns empty.** A TTF price with a
guessed or stale exchange rate is worse than no TTF price: the platform's
"SIMULATED vs real" labelling would call it real while the number was wrong.
The raw EUR/MWh quote and the exact rate used are recorded in `metadata` so any
published figure can be audited back to its inputs.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx

from data_sdk import BaseDataProvider, FetchRequest, ProviderHealth
from schemas import DataClassification, Lineage, ObservationDraft

_YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"
_HEADERS = {"User-Agent": "Mozilla/5.0 (AlphaGasIQ market-data)"}

TTF_SYMBOL = "TTF=F"        # Dutch TTF Natural Gas Calendar Month, quoted EUR/MWh
FX_SYMBOL = "EURUSD=X"      # USD per 1 EUR

# 1 MWh = 3,412,142 BTU = 3.412142 MMBtu (exact from 1 kWh = 3412.142 BTU).
MMBTU_PER_MWH = 3.412142


def eur_mwh_to_usd_mmbtu(eur_per_mwh: float, usd_per_eur: float) -> float:
    """The one conversion this connector exists for. Pure, so it is unit-tested."""
    return (eur_per_mwh * usd_per_eur) / MMBTU_PER_MWH


class YahooTTFProvider(BaseDataProvider):
    provider_id = "ice_live"
    classification = DataClassification.PUBLIC  # delayed public quotes, not licensed
    freshness_sla_seconds = 900  # ~15 min delayed

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client

    async def _quote(self, symbol: str, client: httpx.AsyncClient) -> tuple[float, str] | None:
        """(price, currency) or None. Currency is returned so a Yahoo-side change
        of quoting convention is caught rather than silently mis-converted."""
        resp = await client.get(
            _YAHOO_CHART + symbol, params={"interval": "1d", "range": "5d"},
            headers=_HEADERS, timeout=10.0,
        )
        resp.raise_for_status()
        meta = resp.json()["chart"]["result"][0]["meta"]
        px = meta.get("regularMarketPrice")
        if px is None:
            return None
        return float(px), str(meta.get("currency") or "")

    async def health_check(self) -> ProviderHealth:
        try:
            async with (self._client or httpx.AsyncClient()) as client:
                ttf, fx = await asyncio.gather(
                    self._quote(TTF_SYMBOL, client), self._quote(FX_SYMBOL, client)
                )
            # Degraded, not healthy, when only one leg answers: the conversion
            # needs both, so a half-available feed cannot publish anything.
            return ProviderHealth(
                provider_id=self.provider_id,
                status="healthy" if (ttf and fx) else "degraded",
            )
        except Exception:
            return ProviderHealth(provider_id=self.provider_id, status="unhealthy")

    async def fetch(self, request: FetchRequest) -> list[ObservationDraft]:
        as_of = request.end or datetime.now(timezone.utc)

        # Never raise: a network hiccup must not break boot (same contract as
        # YahooHenryHubProvider) — degrade to an empty, honestly-unavailable curve.
        try:
            async with (self._client or httpx.AsyncClient()) as client:
                ttf, fx = await asyncio.gather(
                    self._quote(TTF_SYMBOL, client),
                    self._quote(FX_SYMBOL, client),
                    return_exceptions=True,
                )
        except Exception:
            return []

        if isinstance(ttf, Exception) or ttf is None:
            return []
        if isinstance(fx, Exception) or fx is None:
            return []  # no FX ⇒ no honest USD/MMBtu conversion ⇒ publish nothing

        eur_per_mwh, ttf_ccy = ttf
        usd_per_eur, fx_ccy = fx

        # Guard the assumptions the conversion rests on. If Yahoo ever changes
        # either quoting convention, publish nothing rather than a wrong number.
        if ttf_ccy and ttf_ccy.upper() != "EUR":
            return []
        if fx_ccy and fx_ccy.upper() != "USD":
            return []

        usd_per_mmbtu = eur_mwh_to_usd_mmbtu(eur_per_mwh, usd_per_eur)

        return [
            ObservationDraft(
                source="YAHOO_ICE",
                source_type=self.classification,
                series_id="TTF.FRONT_MONTH",
                symbol="TTF",
                commodity="NATURAL_GAS",
                category="PRICE",
                sub_category="FUTURES_SETTLEMENT",
                geography="EU",
                location="TTF",
                value=round(usd_per_mmbtu, 3),
                unit="USD_MMBTU",
                observation_time=as_of,
                publication_time=as_of,
                metadata={
                    # Full provenance: the published USD/MMBtu figure can be
                    # re-derived from exactly these three numbers.
                    "raw_price": round(eur_per_mwh, 4),
                    "raw_unit": "EUR_MWH",
                    "fx_pair": FX_SYMBOL,
                    "fx_rate_usd_per_eur": round(usd_per_eur, 6),
                    "mmbtu_per_mwh": MMBTU_PER_MWH,
                    "exchange": "ICE",
                    "vendor": "yahoo",
                },
                lineage=Lineage(transform="YahooTTFProvider.fetch(EUR/MWh→USD/MMBtu)"),
            )
        ]
