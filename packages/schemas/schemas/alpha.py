"""Alpha Intelligence Layer schemas (docs/alpha-intelligence.md).

`Signal` is the foundational unit produced by AlphaSignal(TM): a detected,
materiality-scored change in the natural gas ecosystem that everything downstream
(AlphaImpact, AlphaConsensus, AlphaScenario, AlphaMemory) will eventually consume or
reference. Nothing in this module talks to a database, an LLM, or the network -- it is
a pure data contract, exactly like every other schema in this package.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .agent import Citation
from .enums import DataClassification


class SignalType(str, Enum):
    PRICE_MOVE = "PRICE_MOVE"
    CURVE_CHANGE = "CURVE_CHANGE"
    VOLATILITY_CHANGE = "VOLATILITY_CHANGE"
    PRODUCTION_CHANGE = "PRODUCTION_CHANGE"
    DEMAND_CHANGE = "DEMAND_CHANGE"
    STORAGE_CHANGE = "STORAGE_CHANGE"
    WEATHER_CHANGE = "WEATHER_CHANGE"
    PIPELINE_CONSTRAINT = "PIPELINE_CONSTRAINT"
    PIPELINE_OUTAGE = "PIPELINE_OUTAGE"
    LNG_CHANGE = "LNG_CHANGE"
    POWER_CHANGE = "POWER_CHANGE"
    NEWS_EVENT = "NEWS_EVENT"
    REGULATORY_EVENT = "REGULATORY_EVENT"
    POSITION_CHANGE = "POSITION_CHANGE"
    PORTFOLIO_CHANGE = "PORTFOLIO_CHANGE"
    RISK_LIMIT_APPROACH = "RISK_LIMIT_APPROACH"
    CUSTOMER_DATA_CHANGE = "CUSTOMER_DATA_CHANGE"
    MODEL_DISAGREEMENT = "MODEL_DISAGREEMENT"
    AGENT_DISAGREEMENT = "AGENT_DISAGREEMENT"
    ANOMALY = "ANOMALY"


class SignalDirection(str, Enum):
    """A signal's directional lean -- distinct from `Direction` (LONG/SHORT/SPREAD),
    which describes a trade posture, not a market observation."""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class SignalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"
    EXPIRED = "EXPIRED"


class Signal(BaseModel):
    """A single material change detected by AlphaSignal(TM) (docs/alpha-intelligence.md
    section 2). `organization_id`/`workspace_id` are nullable -- None means a
    platform-wide signal derived from shared public/simulated data, the only kind
    Milestone 1 produces; a future enterprise-data-aware detector can stamp a real
    tenant id without a schema change."""

    id: UUID = Field(default_factory=uuid4)
    organization_id: str | None = None
    workspace_id: str | None = None
    signal_type: SignalType
    category: str
    subcategory: str = ""
    source_ids: list[str] = Field(default_factory=list)
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    effective_at: datetime | None = None
    market: str = "HENRY_HUB"
    geography: str | None = None
    asset_ids: list[str] = Field(default_factory=list)
    headline: str
    description: str
    previous_value: float | None = None
    current_value: float | None = None
    absolute_change: float | None = None
    percent_change: float | None = None
    z_score: float | None = None
    historical_percentile: float | None = None
    materiality_score: float = Field(ge=0, le=100)
    novelty_score: float = Field(ge=0, le=100, default=0.0)
    confidence: float = Field(ge=0, le=1)
    direction: SignalDirection = SignalDirection.NEUTRAL
    time_horizon: str = ""
    data_quality: DataClassification = DataClassification.SIMULATED
    citations: list[Citation] = Field(default_factory=list)
    affected_agents: list[str] = Field(default_factory=list)
    affected_business_functions: list[str] = Field(default_factory=list)
    status: SignalStatus = SignalStatus.ACTIVE
