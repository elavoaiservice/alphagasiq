from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from data_sdk import BaseDataProvider, FetchRequest, ProviderHealth
from schemas import DataClassification, Lineage, ObservationDraft

EIA_BASE_URL = "https://api.eia.gov/v2"

# Licensing metadata (spec §31): EIA is public-domain U.S. government data (17 U.S.C.
# §105) -- confidently marked freely redistributable and usable for AI processing,
# unlike an unknown/unclassified source, which would leave these `None` rather than
# default to permissive.
_PUBLIC_GOV_DATA_LICENSE: dict[str, Any] = {
    "license_type": "PUBLIC_DOMAIN_GOVERNMENT_DATA",
    "public_or_commercial": "PUBLIC",
    "redistribution_allowed": True,
    "ai_processing_allowed": True,
}

# Maps our internal series_id -> EIA route/facets/category/unit. Configurable and
# additive by design: a new EIA series is one more dict entry here, never a change to
# fetch()/normalize() below (spec section 1's "do not hard-code individual series").
#
# Route/facet values below are asserted from EIA's documented v2 API category
# structure (https://www.eia.gov/opendata/browser/natural-gas,
# https://www.eia.gov/opendata/browser/electricity), the same basis the original two
# series (storage, production) and `iso_rto.py`'s `electricity/rto/fuel-type-data`
# route were built from -- this sandbox has no live network access to EIA to confirm
# an exact route/facet-code shape (verified: outbound HTTPS to api.eia.gov is blocked
# by the environment's proxy). A wrong route/facet fails loud and visibly (a non-2xx
# `raise_for_status()`, surfaced through `/admin/data-feeds/{id}/test-connection` and
# `/refresh`'s error-event logging) rather than silently producing wrong numbers --
# never a fabricated value. Treat each new entry below as "ship pending first live
# verification" until an operator with real network access confirms it against
# EIA's API browser.
EIA_SERIES_MAP: dict[str, dict[str, Any]] = {
    "EIA.NG.STORAGE.LOWER48": {
        "route": "natural-gas/stor/wkly/data",
        "frequency": "weekly",
        "category": "STORAGE",
        "sub_category": "WORKING_GAS_IN_STORAGE",
        "geography": "LOWER_48",
        "unit": "BCF",
    },
    "EIA.NG.PRODUCTION.DRY": {
        "route": "natural-gas/prod/sum/data",
        "frequency": "monthly",
        "category": "PRODUCTION",
        "sub_category": "DRY_GAS_PRODUCTION",
        "geography": "US",
        "unit": "BCF",
    },
    "EIA.NG.PRICE.HENRY_HUB_FUTURES_FRONT_MONTH": {
        # NYMEX Henry Hub natural gas futures, contract 1 (front month), daily
        # settlement -- EIA's own published futures-price series, NOT a live
        # exchange/real-time feed and NOT independently confirmed by this codebase
        # to be identical to any distinct "physical spot" index. Labeled
        # FUTURES_FRONT_MONTH, deliberately not "spot", per spec section 9's "never
        # silently mix spot/futures/derived" requirement -- this is the honest name
        # for what EIA actually publishes here.
        "route": "natural-gas/pri/fut/data",
        "frequency": "daily",
        "facets": {"series": "RNGC1"},
        "category": "MARKET_PRICE",
        "sub_category": "HENRY_HUB_FUTURES_FRONT_MONTH",
        "geography": "US",
        "unit": "USD_PER_MMBTU",
    },
    "EIA.NG.CONSUMPTION.RESIDENTIAL": {
        "route": "natural-gas/cons/sum/data",
        "frequency": "monthly",
        "facets": {"process": "VRS", "duoarea": "NUS"},
        "category": "DEMAND",
        "sub_category": "RESIDENTIAL_CONSUMPTION",
        "geography": "US",
        "unit": "MMCF",
    },
    "EIA.NG.CONSUMPTION.COMMERCIAL": {
        "route": "natural-gas/cons/sum/data",
        "frequency": "monthly",
        "facets": {"process": "VCS", "duoarea": "NUS"},
        "category": "DEMAND",
        "sub_category": "COMMERCIAL_CONSUMPTION",
        "geography": "US",
        "unit": "MMCF",
    },
    "EIA.NG.CONSUMPTION.INDUSTRIAL": {
        "route": "natural-gas/cons/sum/data",
        "frequency": "monthly",
        "facets": {"process": "VIN", "duoarea": "NUS"},
        "category": "DEMAND",
        "sub_category": "INDUSTRIAL_CONSUMPTION",
        "geography": "US",
        "unit": "MMCF",
    },
    "EIA.NG.CONSUMPTION.ELECTRIC_POWER": {
        "route": "natural-gas/cons/sum/data",
        "frequency": "monthly",
        "facets": {"process": "VEU", "duoarea": "NUS"},
        "category": "DEMAND",
        "sub_category": "ELECTRIC_POWER_CONSUMPTION",
        "geography": "US",
        "unit": "MMCF",
    },
    "EIA.NG.LNG.EXPORTS": {
        "route": "natural-gas/move/expc/data",
        "frequency": "monthly",
        "category": "LNG",
        "sub_category": "LNG_EXPORTS",
        "geography": "US",
        "unit": "MMCF",
    },
    "EIA.NG.LNG.IMPORTS": {
        # US LNG imports have been near-zero for years (the US is a net LNG
        # exporter) -- included for completeness/symmetry with exports and because
        # a near-zero-but-real figure is still more honest than omitting the series
        # entirely, per spec section 3's explicit "LNG imports" ask.
        "route": "natural-gas/move/impc/data",
        "frequency": "monthly",
        "category": "LNG",
        "sub_category": "LNG_IMPORTS",
        "geography": "US",
        "unit": "MMCF",
    },
}


class EIAProvider(BaseDataProvider):
    """U.S. Energy Information Administration API (v2). PUBLIC data.

    Docs: https://www.eia.gov/opendata/. Requires a free EIA_API_KEY. This connector
    covers the Natural Gas Weekly Storage report and monthly production summary as the
    initial series needed by the balance/storage engines; additional EIA routes can be
    added to `EIA_SERIES_MAP` without touching the fetch/normalize plumbing.
    """

    provider_id = "eia"
    classification = DataClassification.PUBLIC
    freshness_sla_seconds = 7 * 24 * 3600  # weekly release cadence

    def __init__(self, api_key: str | None, client: httpx.AsyncClient | None = None):
        self.api_key = api_key
        self._client = client

    async def health_check(self) -> ProviderHealth:
        if not self.api_key:
            return ProviderHealth(
                provider_id=self.provider_id,
                status="not_configured",
                detail="EIA_API_KEY not set; use seed data or MockCMEProvider-style fallback.",
            )
        return ProviderHealth(provider_id=self.provider_id, status="healthy")

    async def fetch(self, request: FetchRequest) -> list[ObservationDraft]:
        if not self.api_key:
            return []
        drafts: list[ObservationDraft] = []
        async with (self._client or httpx.AsyncClient()) as client:
            for series_id in request.series_ids or list(EIA_SERIES_MAP):
                spec = EIA_SERIES_MAP.get(series_id)
                if not spec:
                    continue
                params: dict[str, Any] = {
                    "api_key": self.api_key,
                    "frequency": spec["frequency"],
                    "data[0]": "value",
                    "sort[0][column]": "period",
                    "sort[0][direction]": "desc",
                    "offset": 0,
                    "length": request.extra.get("length", 52),
                }
                for facet, facet_value in spec.get("facets", {}).items():
                    params[f"facets[{facet}][0]"] = facet_value
                resp = await client.get(f"{EIA_BASE_URL}/{spec['route']}", params=params)
                resp.raise_for_status()
                drafts.extend(self.normalize({"series_id": series_id, "spec": spec, "raw": resp.json()}))
        return drafts

    def normalize(self, raw: Any) -> list[ObservationDraft]:
        series_id: str = raw["series_id"]
        spec: dict[str, str] = raw["spec"]
        payload: dict[str, Any] = raw["raw"]
        records = payload.get("response", {}).get("data", [])
        now = datetime.now(timezone.utc)
        drafts: list[ObservationDraft] = []
        for rec in records:
            period = rec.get("period")
            value = rec.get("value")
            if period is None or value is None:
                continue
            obs_time = _parse_period(period)
            drafts.append(
                ObservationDraft(
                    source="EIA",
                    source_type=self.classification,
                    series_id=series_id,
                    commodity="NATURAL_GAS",
                    category=spec["category"],
                    sub_category=spec.get("sub_category"),
                    geography=spec.get("geography"),
                    value=float(value),
                    unit=spec["unit"],
                    observation_time=obs_time,
                    publication_time=now,
                    metadata={"eia_period": period, "eia_route": spec["route"]},
                    lineage=Lineage(source_url=f"{EIA_BASE_URL}/{spec['route']}"),
                    **_PUBLIC_GOV_DATA_LICENSE,
                )
            )
        return drafts


def _parse_period(period: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(period, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unrecognized EIA period format: {period}")
