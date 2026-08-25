from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from schemas import DataClassification, ObservationDraft


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
