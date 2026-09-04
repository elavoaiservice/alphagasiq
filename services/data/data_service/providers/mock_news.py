from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from data_sdk import BaseDataProvider, FetchRequest, ProviderHealth
from schemas import DataClassification, Lineage, ObservationDraft

SEED_HEADLINES: list[dict[str, Any]] = [
    {
        "headline": "Freeport LNG reports partial feedgas curtailment amid compressor maintenance",
        "event_type": "lng_outage",
        "locations": ["Freeport, TX"],
        "bullish_bearish": "BEARISH",  # bearish for HH price (less feedgas demand)
        "magnitude": 0.35,
    },
    {
        "headline": "Permian producers flag associated gas takeaway constraints as Waha basis widens",
        "event_type": "pipeline_notice",
        "locations": ["Permian Basin, TX"],
        "bullish_bearish": "NEUTRAL",
        "magnitude": 0.2,
    },
    {
        "headline": "NOAA outlook shifts colder for Upper Midwest in week 3-4 forecast",
        "event_type": "weather_change",
        "locations": ["Upper Midwest"],
        "bullish_bearish": "BULLISH",
        "magnitude": 0.45,
    },
    {
        "headline": "Southeast US pipeline operator schedules planned maintenance reducing capacity 0.4 Bcf/d",
        "event_type": "maintenance",
        "locations": ["Southeast US"],
        "bullish_bearish": "BULLISH",
        "magnitude": 0.15,
    },
    {
        "headline": "EIA storage report preview: consensus points to a build near the five-year average",
        "event_type": "storage_issue",
        "locations": ["Lower 48"],
        "bullish_bearish": "NEUTRAL",
        "magnitude": 0.1,
    },
]


class MockNewsProvider(BaseDataProvider):
    """Simulated news feed standing in for a licensed commercial news provider.

    Produces plausible, clearly-`SIMULATED` structured news items so the News
    Intelligence Engine (services/news) is fully exercisable without a paid wire
    subscription.
    """

    provider_id = "mock_news"
    classification = DataClassification.SIMULATED
    freshness_sla_seconds = 300

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(provider_id=self.provider_id, status="healthy")

    async def fetch(self, request: FetchRequest) -> list[ObservationDraft]:
        now = request.end or datetime.now(timezone.utc)
        return self.normalize({"now": now})

    def normalize(self, raw: Any) -> list[ObservationDraft]:
        now: datetime = raw["now"]
        drafts: list[ObservationDraft] = []
        for i, item in enumerate(SEED_HEADLINES):
            published = now - timedelta(hours=i * 3 + 1)
            drafts.append(
                ObservationDraft(
                    source="MOCK_NEWS",
                    source_type=self.classification,
                    series_id=f"NEWS.{item['event_type'].upper()}.{i}",
                    commodity="NATURAL_GAS",
                    category="NEWS_EVENT",
                    sub_category=item["event_type"],
                    geography=item["locations"][0] if item["locations"] else None,
                    value=item["magnitude"],
                    unit="SEVERITY_0_1",
                    observation_time=published,
                    publication_time=published,
                    metadata={
                        "headline": item["headline"],
                        "bullish_bearish": item["bullish_bearish"],
                        "locations": item["locations"],
                        "source_url": "https://example.local/simulated-news",
                    },
                    lineage=Lineage(transform="MockNewsProvider.normalize"),
                )
            )
        return drafts
