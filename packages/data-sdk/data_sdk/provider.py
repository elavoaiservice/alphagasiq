from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field
from schemas import DataClassification, ObservationDraft

FreshnessStatus = Literal["LIVE", "CURRENT", "DELAYED", "STALE", "FAILED", "UNKNOWN"]


def compute_freshness_status(
    *,
    connection_status: str,
    last_observation_time: datetime | None,
    expected_update_frequency_seconds: int | None,
    now: datetime | None = None,
) -> FreshnessStatus:
    """Derives a freshness state from how old the latest known observation is
    relative to the provider's expected update cadence -- rather than treating a
    successful API response as proof of currency. A weekly EIA series that hasn't
    published on schedule is DELAYED/STALE even though the last call succeeded.

    LIVE: age <= 10% of the expected cadence. CURRENT: within the cadence. DELAYED:
    within 2x the cadence. STALE: beyond that. FAILED: the provider's last health
    check reported it unavailable. UNKNOWN: not enough information to judge (never
    configured, or no observation received yet) -- never asserted as a form of
    "healthy" by default.
    """
    if connection_status == "unavailable":
        return "FAILED"
    if connection_status == "not_configured":
        return "UNKNOWN"
    if last_observation_time is None or not expected_update_frequency_seconds or expected_update_frequency_seconds <= 0:
        return "UNKNOWN"

    now = now or datetime.now(timezone.utc)
    obs_time = last_observation_time
    if obs_time.tzinfo is None:
        obs_time = obs_time.replace(tzinfo=timezone.utc)
    age_seconds = (now - obs_time).total_seconds()
    if age_seconds < 0:
        return "UNKNOWN"  # future-dated -- something is wrong upstream, don't assert freshness
    if age_seconds <= expected_update_frequency_seconds * 0.1:
        return "LIVE"
    if age_seconds <= expected_update_frequency_seconds:
        return "CURRENT"
    if age_seconds <= expected_update_frequency_seconds * 2:
        return "DELAYED"
    return "STALE"


class FetchRequest(BaseModel):
    """A normalized request handed to any provider's `fetch()`.

    Providers ignore fields that don't apply to them (e.g. a weather provider ignores
    `symbol`).
    """

    series_ids: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    start: datetime | None = None
    end: datetime | None = None
    geography: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ProviderHealth(BaseModel):
    provider_id: str
    status: str = Field(description="healthy | degraded | unavailable | not_configured")
    detail: str = ""
    checked_at: datetime = Field(default_factory=datetime.utcnow)
    freshness_seconds: float | None = None


class BaseDataProvider(ABC):
    """Common interface every data connector implements.

    Concrete providers (EIA, NOAA, mock CME, mock news, ...) subclass this and:
      1. declare `provider_id` and `classification`
      2. implement `fetch()` to retrieve raw data from the upstream source
      3. implement `normalize()` to turn raw payloads into `ObservationDraft`s, always
         setting `source_type` to `self.classification` and populating `lineage`.

    A provider that requires paid/licensed credentials MUST have a `Mock*Provider`
    sibling that implements the same interface with `classification=SIMULATED` so the
    platform can run end-to-end without a commercial subscription.
    """

    provider_id: str
    classification: DataClassification
    freshness_sla_seconds: int | None = None

    @abstractmethod
    async def health_check(self) -> ProviderHealth: ...

    @abstractmethod
    async def fetch(self, request: FetchRequest) -> list[ObservationDraft]:
        """Fetch + normalize in one call. Implementations typically call an internal
        `_fetch_raw()` then `self.normalize()`."""
        ...

    def normalize(self, raw: Any) -> list[ObservationDraft]:  # pragma: no cover - overridden
        raise NotImplementedError(f"{self.__class__.__name__} must implement normalize()")

    def is_stale(self, latest_observation_time: datetime, *, now: datetime | None = None) -> bool:
        if self.freshness_sla_seconds is None:
            return False
        now = now or datetime.utcnow()
        return (now - latest_observation_time).total_seconds() > self.freshness_sla_seconds


class NotImplementedProvider(BaseDataProvider):
    """Placeholder for connectors defined in docs/data-sources.md but not yet built.

    Reports `not_configured` rather than silently pretending to be healthy, so the
    system-status dashboard reflects reality.
    """

    def __init__(self, provider_id: str, classification: DataClassification):
        self.provider_id = provider_id
        self.classification = classification

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            provider_id=self.provider_id,
            status="not_configured",
            detail="Connector interface defined but not yet implemented.",
        )

    async def fetch(self, request: FetchRequest) -> list[ObservationDraft]:
        return []
