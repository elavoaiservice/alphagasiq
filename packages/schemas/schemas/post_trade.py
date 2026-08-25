from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .enums import OutcomeQuadrant


class PostTradeAnalysis(BaseModel):
    """Generated once a paper position closes (docs/architecture.md "POST-TRADE
    ANALYSIS"). Distinguishes decision quality (was this a well-reasoned, properly
    risk-managed call given what was knowable at the time) from outcome quality (did
    it make money) — the two are not the same thing, and conflating them is exactly
    what this object exists to prevent.
    """

    id: UUID = Field(default_factory=uuid4)
    trade_id: UUID
    expected_outcome: dict = Field(default_factory=dict)
    actual_outcome: dict = Field(default_factory=dict)
    forecast_error: float | None = None
    thesis_accuracy: float = Field(ge=0, le=1)
    timing_accuracy: float = Field(ge=0, le=1)
    risk_accuracy: float = Field(ge=0, le=1)
    model_contribution: dict = Field(default_factory=dict)
    unexpected_events: list[str] = Field(default_factory=list)
    lessons: str = ""
    quadrant: OutcomeQuadrant
    created_at: datetime = Field(default_factory=datetime.utcnow)
