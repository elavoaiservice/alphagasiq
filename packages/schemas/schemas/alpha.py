"""Alpha Intelligence Layer schemas (docs/alpha-intelligence.md).

`Signal` is the foundational unit produced by AlphaSignal(TM): a detected,
materiality-scored change in the natural gas ecosystem that everything downstream
(AlphaImpact, AlphaConsensus, AlphaScenario, AlphaMemory) will eventually consume or
reference. `ImpactAnalysis`/`ImpactEdge` are AlphaImpact(TM)'s output: what a `Signal`
means, expressed as a causal chain from physical event to portfolio/risk implication.
`AgentForecast`/`AgentAlphaScore`/`ConsensusWeight`/`ConsensusView` are AlphaConsensus(TM)'s
schemas: a structured forecast from one agent, that agent's performance rating, its
resulting weight in a consensus computation, and the consensus view itself. Nothing in
this module talks to a database, an LLM, or the network -- it is a pure data contract,
exactly like every other schema in this package.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .agent import Citation
from .enums import AgentType, DataClassification


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


class AgentForecast(BaseModel):
    """A structured directional forecast from one specialized agent for one research
    cycle (docs/alpha-intelligence.md section 6). Extracted from that agent's own
    already-computed `AgentResult.outputs` by `alpha_service.forecast_extractor` --
    not every agent produces one every cycle, only those whose output already
    contains a genuine directional read (a fabricated direction is never invented
    for an agent whose output doesn't already imply one)."""

    id: UUID = Field(default_factory=uuid4)
    agent_id: str
    agent_type: AgentType
    agent_version: str
    organization_id: str | None = None
    forecast_type: str
    target: str
    market: str = "HENRY_HUB"
    horizon: str = ""
    forecast_value: float | None = None
    direction: SignalDirection = SignalDirection.NEUTRAL
    probability: float = Field(ge=0, le=1, default=0.5)
    confidence: float = Field(ge=0, le=1, default=0.0)
    drivers: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime | None = None


class AgentAlphaScore(BaseModel):
    """Agent Alpha Score(TM) (docs/alpha-intelligence.md section 6): how much an
    agent's directional read should be trusted. Milestone 3 is honest about scope --
    only `FORECASTING` has a genuine historical-accuracy figure available today (the
    Quantitative Team's real walk-forward backtests, `method="BACKTESTED_
    DIRECTIONAL_ACCURACY"`); every other agent gets a `"CONFIDENCE_CONSISTENCY_
    PROXY"` score (recent confidence level/consistency/evidence quality) that is
    explicitly NOT a claim of historical predictive accuracy -- no resolved-outcome
    ledger per fundamental agent exists yet (that requires the decision-memory
    infrastructure a later milestone, AlphaMemory, builds). `sample_size=0` means
    "insufficient data", not a low score. Regime/horizon-specific breakdowns (spec's
    "Weather Agent: 93 in extreme cold, 66 in shoulder season") are deferred --
    `components` carries whatever sub-metrics this milestone actually computed."""

    agent_type: AgentType
    score: float = Field(ge=0, le=100)
    method: str
    sample_size: int = 0
    components: dict[str, float] = Field(default_factory=dict)
    computed_at: datetime = Field(default_factory=datetime.utcnow)


class ConsensusWeight(BaseModel):
    agent_type: AgentType
    weight: float = Field(ge=0, le=1)
    alpha_score: float
    forecast_confidence: float
    direction: SignalDirection


class ConsensusView(BaseModel):
    """AlphaConsensus(TM)'s output (docs/alpha-intelligence.md section 6): a
    dynamically (never equal-)weighted aggregation of contributing `AgentForecast`s
    for the same target/market/horizon, weighted by each agent's `AgentAlphaScore`
    and its forecast's own confidence."""

    id: UUID = Field(default_factory=uuid4)
    organization_id: str | None = None
    consensus_type: str
    market: str = "HENRY_HUB"
    target: str
    horizon: str = ""
    consensus_value: float | None = None
    bull_probability: float = Field(ge=0, le=1, default=0.0)
    bear_probability: float = Field(ge=0, le=1, default=0.0)
    neutral_probability: float = Field(ge=0, le=1, default=0.0)
    confidence: float = Field(ge=0, le=1, default=0.0)
    dispersion: float = Field(ge=0, le=1, default=0.0)
    agreement_label: str = "LOW"
    agent_count: int = 0
    agent_weights: list[ConsensusWeight] = Field(default_factory=list)
    leading_agents: list[str] = Field(default_factory=list)
    dissenting_agents: list[str] = Field(default_factory=list)
    drivers: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    market_consensus_value: float | None = None
    variance_vs_market: float | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ScenarioFactorType(str, Enum):
    """The four shock dimensions `risk_service.scenarios.Scenario` already supports.
    AlphaScenario(TM) composes named scenarios and/or custom factors into one
    combined shock rather than introducing a new shock-math engine."""

    PRICE_SHOCK_PCT = "PRICE_SHOCK_PCT"
    DEMAND_SHOCK_BCF_D = "DEMAND_SHOCK_BCF_D"
    SUPPLY_SHOCK_BCF_D = "SUPPLY_SHOCK_BCF_D"
    VOLATILITY_MULTIPLIER = "VOLATILITY_MULTIPLIER"


class ScenarioVariable(BaseModel):
    """One composable shock factor (docs/alpha-intelligence.md section 7). `geography`/
    `asset_id`/`duration` are accepted on the schema for forward compatibility with the
    full spec's per-geography/per-asset/duration-aware modeling, but the Milestone 4
    engine does not yet condition on them -- there is no per-geography position or
    duration-decay data in this codebase today, and fabricating that precision would
    violate this project's "never claim more than is actually computed" rule. They are
    always `None` until that data model exists."""

    factor_type: ScenarioFactorType
    value: float
    geography: str | None = None
    asset_id: str | None = None
    duration: str | None = None


class ScenarioDefinition(BaseModel):
    """A (possibly composed) scenario: zero or more named base scenarios from
    `risk_service.scenarios.SCENARIOS` stacked with zero or more custom
    `ScenarioVariable`s. `alpha_service.scenario_engine.ScenarioEngine.compose()` turns
    this into a single `risk_service.scenarios.Scenario` by summing/multiplying the
    matching factor types -- see that module's docstring for the exact composition rule."""

    id: UUID = Field(default_factory=uuid4)
    name: str
    description: str = ""
    base_scenario_ids: list[str] = Field(default_factory=list)
    variables: list[ScenarioVariable] = Field(default_factory=list)


class ScenarioRunResult(BaseModel):
    """One persisted execution of a `ScenarioDefinition` against the paper-trading
    book (docs/alpha-intelligence.md section 7). Wraps
    `risk_service.scenarios.ScenarioResult` (the underlying, already-tested P&L/VaR
    math, reused rather than duplicated) with composition metadata and persistence
    identity."""

    id: UUID = Field(default_factory=uuid4)
    organization_id: str | None = None
    scenario_name: str
    scenario_description: str = ""
    base_scenario_ids: list[str] = Field(default_factory=list)
    price_shock_pct: float = 0.0
    demand_shock_bcf_d: float = 0.0
    supply_shock_bcf_d: float = 0.0
    volatility_multiplier: float = 1.0
    portfolio_pnl: float
    strategy_pnl: dict[str, float] = Field(default_factory=dict)
    margin_impact: float
    var_impact: float
    largest_risk_contributor: str
    requested_by: str | None = None
    run_at: datetime = Field(default_factory=datetime.utcnow)


class ScenarioComparison(BaseModel):
    """The result of running several scenarios (typically the whole standing library)
    against the same book in one pass, ranked worst-to-best by portfolio P&L impact --
    the "base vs. A vs. B vs. C" comparison from docs/alpha-intelligence.md section 7."""

    id: UUID = Field(default_factory=uuid4)
    organization_id: str | None = None
    run_ids: list[UUID] = Field(default_factory=list)
    worst_case_scenario_name: str = ""
    worst_case_portfolio_pnl: float = 0.0
    best_case_scenario_name: str = ""
    best_case_portfolio_pnl: float = 0.0
    ranked_scenario_names: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
