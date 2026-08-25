from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .enums import DataClassification


class Lineage(BaseModel):
    """Traces an observation back to the exact raw payload(s) it derives from."""

    upstream_observation_ids: list[UUID] = Field(default_factory=list)
    raw_payload_ref: str | None = Field(
        default=None, description="Object-store key for the archived raw provider response"
    )
    source_url: str | None = None
    transform: str | None = Field(
        default=None, description="Name/version of the normalization step applied"
    )


class ObservationDraft(BaseModel):
    """What a `BaseDataProvider` returns before it is persisted as a `TimeSeriesObservation`.

    Deliberately excludes `id`, `received_time`, `created_at` — those are assigned at
    persistence time.
    """

    source: str
    source_type: DataClassification
    series_id: str
    symbol: str | None = None
    commodity: str = "NATURAL_GAS"
    category: str
    sub_category: str | None = None
    geography: str | None = None
    location: str | None = None
    value: float
    unit: str
    observation_time: datetime
    publication_time: datetime
    revision_number: int = 0
    quality_score: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    lineage: Lineage = Field(default_factory=Lineage)


class TimeSeriesObservation(ObservationDraft):
    """The canonical, persisted row. See docs/database-schema.md."""

    id: UUID = Field(default_factory=uuid4)
    received_time: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)
