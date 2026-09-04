from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .enums import Direction, InstrumentType, RecommendedAction


class TradeIdea(BaseModel):
    """Output of a Strategy Team agent. Strategies never submit orders — this is a
    proposal that must pass the AI Investment Committee, the Risk Governor, and human
    approval before it can become a paper order."""

    trade_id: UUID = Field(default_factory=uuid4)
    # Tenant-isolation retrofit (docs/alpha-intelligence.md section 11.1, Milestone
    # 9): schema readiness only. `None` (the only value ever set today) is unchanged
    # behavior -- every trade idea today comes from the single process-wide
    # `AppState`'s system-generated research cycle (`worker.py`), never from a
    # per-organization submission path, so real per-org separate trading books
    # remain future work, not something this field alone provides.
    organization_id: str | None = None
    strategy: str
    instrument: str
    instrument_type: InstrumentType
    direction: Direction
    entry: float
    target: float
    stop_or_invalidation: float
    time_horizon: str
    expected_return: float
    expected_loss: float
    probability_success: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    thesis: str
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    invalidation_conditions: list[str] = Field(default_factory=list)
    supporting_data: list[str] = Field(default_factory=list)
    source_citations: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime | None = None

    # Explainability payload (WHAT/WHY/WHY NOW/... ) is derived, not stored redundantly;
    # see services/agents/app/explainability.py::build_explainability(trade_idea).


class InvestmentCommitteeDecision(BaseModel):
    original_trade: TradeIdea
    bull_case: str
    bear_case: str
    skeptic_case: str
    data_quality_assessment: str
    portfolio_effect: str
    consensus_score: float = Field(ge=0, le=1)
    unresolved_questions: list[str] = Field(default_factory=list)
    recommended_action: RecommendedAction
    decided_at: datetime = Field(default_factory=datetime.utcnow)
