from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from data_sdk import BaseDataProvider, FetchRequest, ProviderHealth
from schemas import DataClassification, Lineage, ObservationDraft

NWS_BASE_URL = "https://api.weather.gov"

# Licensing metadata (spec §31): NOAA/NWS is public-domain U.S. government data (17
# U.S.C. §105) -- confidently marked freely redistributable and usable for AI
# processing, matching `eia.py`'s `_PUBLIC_GOV_DATA_LICENSE`.
_PUBLIC_GOV_DATA_LICENSE: dict[str, Any] = {
    "license_type": "PUBLIC_DOMAIN_GOVERNMENT_DATA",
    "public_or_commercial": "PUBLIC",
    "redistribution_allowed": True,
    "ai_processing_allowed": True,
}

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
            forecast_by_region: dict[str, list[ObservationDraft]] = {}
            for region in regions:
                station = REGION_STATIONS.get(region)
                if not station:
                    continue
                resp = await client.get(f"{NWS_BASE_URL}/gridpoints/{station}/forecast")
                resp.raise_for_status()
                region_drafts = self.normalize({"region": region, "raw": resp.json()})
                forecast_by_region[region] = region_drafts
                drafts.extend(region_drafts)

            alerts_resp = await client.get(f"{NWS_BASE_URL}/alerts/active")
            alerts_resp.raise_for_status()
            drafts.extend(self._normalize_alerts(alerts_resp.json()))

        drafts.extend(_national_degree_day_average(forecast_by_region))
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
                    **_PUBLIC_GOV_DATA_LICENSE,
                )
            )
        return drafts

    def _normalize_alerts(self, payload: dict[str, Any]) -> list[ObservationDraft]:
        """NWS's active-alerts feed (`/alerts/active`, a stable public GeoJSON
        endpoint covering winter storms, extreme heat/cold, freeze, hurricanes, and
        other severe weather) -- surfaced as one observation per active alert so
        AlphaSignal can detect e.g. a new winter storm warning the same way it
        detects a storage surprise: from a real, cited, quantifiable event, not an
        LLM's judgment call."""
        now = datetime.now(timezone.utc)
        drafts: list[ObservationDraft] = []
        for feature in payload.get("features", []):
            props = feature.get("properties", {})
            onset = props.get("onset") or props.get("effective")
            event = props.get("event")
            if onset is None or event is None:
                continue
            drafts.append(
                ObservationDraft(
                    source="NOAA_NWS",
                    source_type=self.classification,
                    series_id=f"NOAA.ALERT.{props.get('id', event)}",
                    commodity="NATURAL_GAS",
                    category="WEATHER",
                    sub_category="SEVERE_WEATHER_ALERT",
                    geography=props.get("areaDesc"),
                    value=1.0,  # presence indicator -- alerts are categorical, not a magnitude
                    unit="ALERT_ACTIVE",
                    observation_time=datetime.fromisoformat(onset),
                    publication_time=now,
                    metadata={
                        "event": event,
                        "severity": props.get("severity"),
                        "certainty": props.get("certainty"),
                        "urgency": props.get("urgency"),
                        "headline": props.get("headline"),
                        "expires": props.get("expires"),
                    },
                    lineage=Lineage(source_url=f"{NWS_BASE_URL}/alerts/active"),
                    **_PUBLIC_GOV_DATA_LICENSE,
                )
            )
        return drafts


def _national_degree_day_average(forecast_by_region: dict[str, list[ObservationDraft]]) -> list[ObservationDraft]:
    """A simple unweighted average of each region's nearest forecast HDD/CDD --
    explicitly NOT a population-weighted national figure (that would require
    per-station population weights this connector doesn't have). Labeled
    `sub_category="NATIONAL_HDD_CDD_UNWEIGHTED_APPROXIMATION"` so nothing downstream
    mistakes this for the more precise population-weighted product utilities/EIA
    themselves publish -- an honest approximation, not a claim of higher precision."""
    now = datetime.now(timezone.utc)
    nearest_per_region: list[ObservationDraft] = []
    for region, region_drafts in forecast_by_region.items():
        if region == "US_NATIONAL" or not region_drafts:
            continue
        nearest_per_region.append(min(region_drafts, key=lambda d: d.observation_time))
    if not nearest_per_region:
        return []
    avg_hdd = sum(d.metadata["hdd"] for d in nearest_per_region) / len(nearest_per_region)
    avg_cdd = sum(d.metadata["cdd"] for d in nearest_per_region) / len(nearest_per_region)
    obs_time = min(d.observation_time for d in nearest_per_region)
    return [
        ObservationDraft(
            source="NOAA_NWS",
            source_type=DataClassification.PUBLIC,
            series_id="NOAA.HDD_CDD.NATIONAL_APPROXIMATION",
            commodity="NATURAL_GAS",
            category="WEATHER",
            sub_category="NATIONAL_HDD_CDD_UNWEIGHTED_APPROXIMATION",
            geography="US_NATIONAL",
            value=avg_hdd,
            unit="HDD",
            observation_time=obs_time,
            publication_time=now,
            metadata={"hdd": avg_hdd, "cdd": avg_cdd, "regions_averaged": sorted(forecast_by_region)},
            lineage=Lineage(source_url=f"{NWS_BASE_URL}/gridpoints"),
            **_PUBLIC_GOV_DATA_LICENSE,
        )
    ]


def degree_days(temp_f: float, base: float = 65.0) -> tuple[float, float]:
    """Standard HDD/CDD calc relative to a 65F base."""
    hdd = max(0.0, base - temp_f)
    cdd = max(0.0, temp_f - base)
    return hdd, cdd
