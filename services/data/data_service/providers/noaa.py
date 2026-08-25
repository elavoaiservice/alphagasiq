from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from data_sdk import BaseDataProvider, FetchRequest, ProviderHealth
from schemas import DataClassification, Lineage, ObservationDraft

NWS_BASE_URL = "https://api.weather.gov"

# Representative population-weighted demand regions we track forecasts for. Real grid
# points would be looked up per-station; these are illustrative NWS forecast offices
# used as regional proxies for the initial connector.
REGION_STATIONS: dict[str, str] = {
    "US_NATIONAL": "OKX",  # placeholder proxy station; national HDD/CDD is a
    "NORTHEAST": "OKX",
    "MIDWEST": "LOT",
    "SOUTH": "HGX",
    "WEST": "LOX",
}


class NOAAProvider(BaseDataProvider):
    """NOAA / National Weather Service API. PUBLIC data, no API key required, but a
    contact token (NOAA_API_TOKEN) is recommended per NWS API etiquette and is sent as
    a descriptive User-Agent header.

    Docs: https://www.weather.gov/documentation/services-web-api
    """

    provider_id = "noaa_nws"
    classification = DataClassification.PUBLIC
    freshness_sla_seconds = 6 * 3600  # forecasts update multiple times per day

    def __init__(self, contact_token: str | None, client: httpx.AsyncClient | None = None):
        self.contact_token = contact_token
        self._client = client

    def _headers(self) -> dict[str, str]:
        contact = self.contact_token or "dev@alphagasiq.local"
        return {"User-Agent": f"AlphaGasIQ ({contact})", "Accept": "application/geo+json"}

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(provider_id=self.provider_id, status="healthy")

    async def fetch(self, request: FetchRequest) -> list[ObservationDraft]:
        regions = request.extra.get("regions") or list(REGION_STATIONS)
        drafts: list[ObservationDraft] = []
        async with (self._client or httpx.AsyncClient(headers=self._headers())) as client:
            for region in regions:
                station = REGION_STATIONS.get(region)
                if not station:
                    continue
                resp = await client.get(f"{NWS_BASE_URL}/gridpoints/{station}/forecast")
                resp.raise_for_status()
                drafts.extend(self.normalize({"region": region, "raw": resp.json()}))
        return drafts

    def normalize(self, raw: Any) -> list[ObservationDraft]:
        region: str = raw["region"]
        payload: dict[str, Any] = raw["raw"]
        periods = payload.get("properties", {}).get("periods", [])
        now = datetime.now(timezone.utc)
        drafts: list[ObservationDraft] = []
        for period in periods:
            temp_f = period.get("temperature")
            start = period.get("startTime")
            if temp_f is None or start is None:
                continue
            obs_time = datetime.fromisoformat(start)
            hdd, cdd = degree_days(temp_f)
            drafts.append(
                ObservationDraft(
                    source="NOAA_NWS",
                    source_type=self.classification,
                    series_id=f"NOAA.TEMP.{region}",
                    commodity="NATURAL_GAS",
                    category="WEATHER",
                    sub_category="FORECAST_TEMPERATURE",
                    geography=region,
                    value=float(temp_f),
                    unit="DEGF",
                    observation_time=obs_time,
                    publication_time=now,
                    metadata={
                        "hdd": hdd,
                        "cdd": cdd,
                        "period_name": period.get("name"),
                        "is_daytime": period.get("isDaytime"),
                    },
                    lineage=Lineage(source_url=f"{NWS_BASE_URL}/gridpoints"),
                )
            )
        return drafts


def degree_days(temp_f: float, base: float = 65.0) -> tuple[float, float]:
    """Standard HDD/CDD calc relative to a 65F base."""
    hdd = max(0.0, base - temp_f)
    cdd = max(0.0, temp_f - base)
    return hdd, cdd
