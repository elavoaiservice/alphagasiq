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

    # Phase 1 free-data-feed integration (docs/data-sources.md): licensing metadata,
    # populated conservatively per source at connector normalize() time -- `None`
    # means "unknown," never inferred. Public-domain U.S. government data (EIA, NOAA)
    # sets these `True`/`"PUBLIC"`; a future licensed connector (CME, ICE, ...) would
    # set them per that provider's actual license terms, never left to default to
    # permissive.
    license_type: str | None = None
    public_or_commercial: str | None = Field(default=None, description="PUBLIC | COMMERCIAL | None (unknown)")
    redistribution_allowed: bool | None = None
    ai_processing_allowed: bool | None = None


class TimeSeriesObservation(ObservationDraft):
    """The canonical, persisted row. See docs/database-schema.md.

    `revision_time`/`valid_from`/`valid_to` (docs/alpha-intelligence.md section 9,
    AlphaReplay(TM)) complete the bitemporal model: `observation_time`/
    `publication_time` already capture *when the world was in this state* vs. *when
    it became knowable*; `valid_from`/`valid_to` additionally track *which revision
    of this observation_time+series_id was the current best estimate at any given
    moment* -- when a later revision arrives for the same series_id+observation_time,
    the prior revision's `valid_to` is set to the new revision's `publication_time`
    rather than silently overwritten, so an "as known at <timestamp>" query can
    still recover exactly what was believed then, corrections included. `valid_to`
    is `None` only for the current (latest) revision. `revision_time` is when this
    specific revision was recorded, distinct from `publication_time` (when the new
    information source-published it) for the rare case those differ.
    """

    id: UUID = Field(default_factory=uuid4)
    received_time: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    revision_time: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
