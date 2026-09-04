from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from data_sdk import BaseDataProvider, FetchRequest, ProviderHealth
from schemas import DataClassification, Lineage, ObservationDraft


class RSSNewsProvider(BaseDataProvider):
    """Generic RSS/Atom feed connector for PUBLIC news sources (e.g. agency press
    releases, regulator announcements). Only ingests feeds the operator explicitly
    configures — never scrapes a site outside its published feed / terms of service.
    """

    provider_id = "rss_news"
    classification = DataClassification.PUBLIC
    freshness_sla_seconds = 900

    def __init__(self, feed_urls: list[str], client: httpx.AsyncClient | None = None):
        self.feed_urls = feed_urls
        self._client = client

    async def health_check(self) -> ProviderHealth:
        status = "healthy" if self.feed_urls else "not_configured"
        return ProviderHealth(provider_id=self.provider_id, status=status)

    async def fetch(self, request: FetchRequest) -> list[ObservationDraft]:
        drafts: list[ObservationDraft] = []
        async with (self._client or httpx.AsyncClient()) as client:
            for url in self.feed_urls:
                resp = await client.get(url)
                resp.raise_for_status()
                drafts.extend(self.normalize({"url": url, "xml": resp.text}))
        return drafts

    def normalize(self, raw: Any) -> list[ObservationDraft]:
        url: str = raw["url"]
        xml_text: str = raw["xml"]
        root = ET.fromstring(xml_text)
        drafts: list[ObservationDraft] = []
        now = datetime.now(timezone.utc)
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or url).strip()
            pub_date_raw = item.findtext("pubDate")
            published = _parse_rss_date(pub_date_raw) if pub_date_raw else now
            if not title:
                continue
            drafts.append(
                ObservationDraft(
                    source="RSS",
                    source_type=self.classification,
                    series_id=f"RSS.{hash(link) & 0xFFFFFFFF}",
                    commodity="NATURAL_GAS",
                    category="NEWS_EVENT",
                    sub_category="RSS_ITEM",
                    value=0.0,
                    unit="SEVERITY_0_1",
                    observation_time=published,
                    publication_time=published,
                    metadata={"headline": title, "source_url": link, "feed_url": url},
                    lineage=Lineage(source_url=link),
                )
            )
        return drafts


def _parse_rss_date(value: str) -> datetime:
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
