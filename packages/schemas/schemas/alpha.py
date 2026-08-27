"""Alpha Intelligence Layer schemas (docs/alpha-intelligence.md).

`Signal` is the foundational unit produced by AlphaSignal(TM): a detected,
materiality-scored change in the natural gas ecosystem that everything downstream
(AlphaImpact, AlphaConsensus, AlphaScenario, AlphaMemory) will eventually consume or
reference. `ImpactAnalysis`/`ImpactEdge` are AlphaImpact(TM)'s output: what a `Signal`
means, expressed as a causal chain from physical event to portfolio/risk implication.
Nothing in this module talks to a database, an LLM, or the network -- it is a pure data
contract, exactly like every other schema in this package.
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


class ImpactCategory(str, Enum):
    """The fixed causal-chain stages AlphaImpact(TM) reasons through (spec's
    EVENT -> PHYSICAL IMPACT -> SUPPLY/DEMAND -> STORAGE -> REGIONAL -> PRICE/CURVE ->
    STRATEGY -> PORTFOLIO -> RISK). Not every signal type traverses every stage --
    `impact_engine.py`'s chain skeletons pick the subset that actually applies."""

    PHYSICAL = "PHYSICAL"
    SUPPLY_DEMAND = "SUPPLY_DEMAND"
    STORAGE = "STORAGE"
    REGIONAL = "REGIONAL"
    PRICE_CURVE = "PRICE_CURVE"
    STRATEGY = "STRATEGY"
    PORTFOLIO = "PORTFOLIO"
    RISK = "RISK"


class ImpactEdge(BaseModel):
    """One link in an `ImpactAnalysis`'s causal chain. Each link carries its own
    confidence/magnitude (both decay along the chain -- later stages are always at
    least as uncertain as earlier ones, never more confident) and the evidence it's
    grounded in, so the UI can render the chain as a graph rather than a single opaque
    verdict (docs/alpha-intelligence.md section 5)."""

    id: UUID = Field(default_factory=uuid4)
    sequence_index: int
    category: ImpactCategory
    from_node: str
    to_node: str
    description: str
    confidence: float = Field(ge=0, le=1)
    magnitude: float | None = Field(default=None, ge=0, le=100)
    supporting_evidence: list[str] = Field(default_factory=list)


class ImpactAnalysis(BaseModel):
    """AlphaImpact(TM)'s output for one `Signal` (docs/alpha-intelligence.md section 5):
    what the signal means, not just that it happened. `bullish_bearish`/`magnitude` are
    carried forward from the originating signal's own `direction`/`materiality_score` in
    Milestone 2 -- an independently-modeled impact magnitude (distinct from the
    triggering signal's own materiality) is future work, documented here rather than
    silently assumed. `affected_contracts`/enterprise-personalized implications are
    always empty until the Enterprise Data Platform milestones exist."""

    id: UUID = Field(default_factory=uuid4)
    signal_id: UUID
    organization_id: str | None = None
    event_type: SignalType
    physical_impact: str
    supply_impact_bcf_day: float | None = None
    demand_impact_bcf_day: float | None = None
    storage_impact_bcf: float | None = None
    expected_duration: str = ""
    affected_geographies: list[str] = Field(default_factory=list)
    affected_assets: list[str] = Field(default_factory=list)
    affected_markets: list[str] = Field(default_factory=list)
    affected_contracts: list[str] = Field(default_factory=list)
    basis_implications: str = ""
    curve_implications: str = ""
    volatility_implications: str = ""
    portfolio_implications: str = ""
    risk_implications: str = ""
    bullish_bearish: SignalDirection = SignalDirection.NEUTRAL
    magnitude: float = Field(ge=0, le=100, default=0.0)
    confidence: float = Field(ge=0, le=1, default=0.0)
    assumptions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    alternative_interpretations: list[str] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    agent_contributors: list[str] = Field(default_factory=list)
    chain: list[ImpactEdge] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
