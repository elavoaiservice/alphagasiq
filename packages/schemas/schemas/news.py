from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class NewsEvent(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    headline: str
    source: str
    source_url: str
    published_at: datetime
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    event_type: str
    entities: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    summary: str
    supply_impact_bcf_day: float = 0.0
    demand_impact_bcf_day: float = 0.0
    expected_duration: str | None = None
    affected_markets: list[str] = Field(default_factory=list)
    bullish_bearish: str = Field(description="BULLISH | BEARISH | NEUTRAL")
    magnitude: float = Field(ge=0, le=1, description="normalized 0-1 severity")
    confidence: float = Field(ge=0, le=1)
    citations: list[str] = Field(default_factory=list)
