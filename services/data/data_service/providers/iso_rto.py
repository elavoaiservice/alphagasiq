from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from data_sdk import BaseDataProvider, FetchRequest, ProviderHealth
from schemas import DataClassification, Lineage, ObservationDraft

EIA_BASE_URL = "https://api.eia.gov/v2"

# ISO/RTO balancing-authority codes this connector tracks natural-gas-fueled
# generation for, via EIA's v2 Electric Power Operations (EIA-930) hourly grid-monitor
# route (docs: https://www.eia.gov/opendata/browser/electricity/rto/fuel-type-data).
TRACKED_RESPONDENTS: list[str] = ["PJM", "CISO", "ERCO", "MISO", "SWPP"]

_NATURAL_GAS_FUEL_CODE = "NG"
# EIA-930's sibling "region-data" route (spec section 7's "System load" ask) --
# `facets[type]=D` is actual (not forecast) demand. Same "asserted from EIA's
# documented v2 category structure, not live-verified" caveat as `eia.py`'s new
# series applies here too.
_DEMAND_ROUTE = "electricity/rto/region-data/data"
_ACTUAL_DEMAND_TYPE_CODE = "D"

# Licensing metadata (spec §31), matching eia.py/noaa.py's identical public-domain
# government-data posture -- omitted here in the original round, added now for
# consistency across every EIA-sourced connector.
_PUBLIC_GOV_DATA_LICENSE: dict[str, Any] = {
    "license_type": "PUBLIC_DOMAIN_GOVERNMENT_DATA",
    "public_or_commercial": "PUBLIC",
    "redistribution_allowed": True,
    "ai_processing_allowed": True,
}


class ISORTOProvider(BaseDataProvider):
    """EIA's Electric Power Operations (EIA-930) hourly grid-monitor data (v2 API),
    filtered to natural-gas-fueled generation for the major US ISOs/RTOs (PJM, CAISO,
    ERCOT, MISO, SPP). PUBLIC data; requires the same free `EIA_API_KEY` the EIA
    connector already uses (identical `api.eia.gov` v2 base URL and auth convention —
    the request/response plumbing this connector reuses is the same one already
    proven correct by `EIAProvider`).

    Deliberately built on EIA's own aggregation of ISO/RTO-reported generation-by-fuel
    data rather than each ISO's own bespoke market-data API (e.g. CAISO's OASIS,
    ERCOT's public reports) — one connector covers every major RTO's natural-gas burn
    for power generation instead of one bespoke integration per ISO.
    """

    provider_id = "iso_rto_public"
    classification = DataClassification.PUBLIC
    freshness_sla_seconds = 6 * 3600  # EIA-930 publishes with roughly a day's lag, refreshed several times/day
    license_type = _PUBLIC_GOV_DATA_LICENSE["license_type"]
    public_or_commercial = _PUBLIC_GOV_DATA_LICENSE["public_or_commercial"]
    redistribution_allowed = _PUBLIC_GOV_DATA_LICENSE["redistribution_allowed"]
    ai_processing_allowed = _PUBLIC_GOV_DATA_LICENSE["ai_processing_allowed"]

    def __init__(self, api_key: str | None, client: httpx.AsyncClient | None = None):
        self.api_key = api_key
        self._client = client

    async def health_check(self) -> ProviderHealth:
        if not self.api_key:
            return ProviderHealth(
                provider_id=self.provider_id,
                status="not_configured",
                detail="EIA_API_KEY not set; ISO/RTO fuel-type data uses the same EIA v2 credential.",
            )
        return ProviderHealth(provider_id=self.provider_id, status="healthy")

    async def fetch(self, request: FetchRequest) -> list[ObservationDraft]:
        if not self.api_key:
            return []
        respondents = request.extra.get("respondents") or TRACKED_RESPONDENTS
        drafts: list[ObservationDraft] = []
        async with (self._client or httpx.AsyncClient()) as client:
            for respondent in respondents:
                gen_params = {
                    "api_key": self.api_key,
                    "frequency": "hourly",
                    "data[0]": "value",
                    "facets[respondent][0]": respondent,
                    "facets[fueltype][0]": _NATURAL_GAS_FUEL_CODE,
                    "sort[0][column]": "period",
                    "sort[0][direction]": "desc",
                    "offset": 0,
                    "length": 24,
                }
                resp = await client.get(f"{EIA_BASE_URL}/electricity/rto/fuel-type-data/data", params=gen_params)
                resp.raise_for_status()
                drafts.extend(self.normalize({"respondent": respondent, "raw": resp.json()}))

                demand_params = {
                    "api_key": self.api_key,
                    "frequency": "hourly",
                    "data[0]": "value",
                    "facets[respondent][0]": respondent,
                    "facets[type][0]": _ACTUAL_DEMAND_TYPE_CODE,
                    "sort[0][column]": "period",
                    "sort[0][direction]": "desc",
                    "offset": 0,
                    "length": 24,
                }
                demand_resp = await client.get(f"{EIA_BASE_URL}/{_DEMAND_ROUTE}", params=demand_params)
                demand_resp.raise_for_status()
                drafts.extend(self._normalize_demand({"respondent": respondent, "raw": demand_resp.json()}))
        return drafts

    def normalize(self, raw: Any) -> list[ObservationDraft]:
        respondent: str = raw["respondent"]
        payload: dict[str, Any] = raw["raw"]
        records = payload.get("response", {}).get("data", [])
        now = datetime.now(timezone.utc)
        drafts: list[ObservationDraft] = []
        for rec in records:
            period = rec.get("period")
            value = rec.get("value")
            if period is None or value is None:
                continue
            drafts.append(
                ObservationDraft(
                    source="EIA_930",
                    source_type=self.classification,
                    series_id=f"EIA930.NG_GENERATION.{respondent}",
                    commodity="NATURAL_GAS",
                    category="POWER_BURN",
                    sub_category="RTO_NATURAL_GAS_GENERATION",
                    geography=respondent,
                    value=float(value),
                    unit=rec.get("value-units") or "megawatthours",
                    observation_time=_parse_hourly_period(period),
                    publication_time=now,
                    metadata={"respondent_name": rec.get("respondent-name"), "eia_period": period},
                    lineage=Lineage(source_url=f"{EIA_BASE_URL}/electricity/rto/fuel-type-data/data"),
                    **_PUBLIC_GOV_DATA_LICENSE,
                )
            )
        return drafts

    def _normalize_demand(self, raw: Any) -> list[ObservationDraft]:
        respondent: str = raw["respondent"]
        payload: dict[str, Any] = raw["raw"]
        records = payload.get("response", {}).get("data", [])
        now = datetime.now(timezone.utc)
        drafts: list[ObservationDraft] = []
        for rec in records:
            period = rec.get("period")
            value = rec.get("value")
            if period is None or value is None:
                continue
            drafts.append(
                ObservationDraft(
                    source="EIA_930",
                    source_type=self.classification,
                    series_id=f"EIA930.DEMAND.{respondent}",
                    commodity="NATURAL_GAS",
                    category="POWER",
                    sub_category="RTO_ELECTRICITY_DEMAND",
                    geography=respondent,
                    value=float(value),
                    unit=rec.get("value-units") or "megawatthours",
                    observation_time=_parse_hourly_period(period),
                    publication_time=now,
                    metadata={"respondent_name": rec.get("respondent-name"), "eia_period": period},
                    lineage=Lineage(source_url=f"{EIA_BASE_URL}/{_DEMAND_ROUTE}"),
                    **_PUBLIC_GOV_DATA_LICENSE,
                )
            )
        return drafts


def _parse_hourly_period(period: str) -> datetime:
    # EIA-930 hourly periods look like "2026-08-25T14" (UTC hour, no minutes/seconds).
    for fmt in ("%Y-%m-%dT%H", "%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(period, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Unrecognized EIA-930 period format: {period}")
