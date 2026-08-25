from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from data_sdk import BaseDataProvider, FetchRequest, ProviderHealth
from schemas import DataClassification, Lineage, ObservationDraft

EIA_BASE_URL = "https://api.eia.gov/v2"

# Maps our internal series_id -> (EIA route, EIA data column, category/sub_category, unit)
EIA_SERIES_MAP: dict[str, dict[str, str]] = {
    "EIA.NG.STORAGE.LOWER48": {
        "route": "natural-gas/stor/wkly/data",
        "category": "STORAGE",
        "sub_category": "WORKING_GAS_IN_STORAGE",
        "geography": "LOWER_48",
        "unit": "BCF",
    },
    "EIA.NG.PRODUCTION.DRY": {
        "route": "natural-gas/prod/sum/data",
        "category": "PRODUCTION",
        "sub_category": "DRY_GAS_PRODUCTION",
        "geography": "US",
        "unit": "BCF",
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
                    "frequency": "weekly" if "wkly" in spec["route"] else "monthly",
                    "data[0]": "value",
                    "sort[0][column]": "period",
                    "sort[0][direction]": "desc",
                    "offset": 0,
                    "length": 52,
                }
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
