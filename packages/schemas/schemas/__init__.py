"""Canonical Pydantic schemas shared across every AlphaGasIQ service.

Nothing in this package talks to a database, an LLM, or the network — it is
pure data contracts so every service (and the frontend, via generated
OpenAPI types) agrees on the shape of an Observation, an AgentResult, a
TradeIdea, and so on.
"""

from .enums import (
    AgentStatus,
    AgentType,
    ApprovalAction,
    ApprovalState,
    DataClassification,
    Direction,
    InstrumentType,
    OutcomeQuadrant,
    RecommendedAction,
    RiskVerdict,
    Regime,
)
from .observation import Lineage, ObservationDraft, TimeSeriesObservation
from .agent import AgentError, AgentResult, Citation, DataSourceRef
from .trading import InvestmentCommitteeDecision, TradeIdea
from .risk import RiskCheckResult, RiskLimits, RiskRuleOutcome
from .news import NewsEvent
from .weather import WeatherDemandImpact
from .fundamentals import GasBalanceDaily, StorageForecast
from .events import DomainEvent, EventType, topic_for_event_type
from .post_trade import PostTradeAnalysis
from .quant import BacktestResult, ForecastHorizon, ModelType, PriceForecast, RegimeResult, RelativeValueSignal
from .alpha import (
    AgentAlphaScore,
    AgentForecast,
    AsOfReplayResult,
    ConsensusView,
    ConsensusWeight,
    ImpactAnalysis,
    ImpactCategory,
    ImpactEdge,
    IntelligenceBrief,
    LessonProposal,
    LessonProposalStatus,
    MemoryRecord,
    MemoryType,
    ReplayMode,
    ScenarioComparison,
    ScenarioDefinition,
    ScenarioFactorType,
    ScenarioRunResult,
    ScenarioVariable,
    Signal,
    SignalDirection,
    SignalStatus,
    SignalType,
)
from .enterprise import (
    EnterpriseConnectorType,
    EnterpriseDataDomain,
    EnterpriseDataEntitlement,
    EnterpriseDataClassification,
    EnterpriseDataset,
    EnterpriseDataSource,
    EnterpriseEntitlementPrincipalType,
    EnterpriseSourceStatus,
    Workspace,
)

__all__ = [
    "AgentStatus",
    "AgentType",
    "ApprovalAction",
    "ApprovalState",
    "DataClassification",
    "Direction",
    "InstrumentType",
    "OutcomeQuadrant",
    "RecommendedAction",
    "RiskVerdict",
    "Regime",
    "Lineage",
    "ObservationDraft",
    "TimeSeriesObservation",
    "AgentError",
    "AgentResult",
    "Citation",
    "DataSourceRef",
    "InvestmentCommitteeDecision",
    "TradeIdea",
    "RiskCheckResult",
    "RiskLimits",
    "RiskRuleOutcome",
    "NewsEvent",
    "WeatherDemandImpact",
    "GasBalanceDaily",
    "StorageForecast",
    "DomainEvent",
    "EventType",
    "topic_for_event_type",
    "PostTradeAnalysis",
    "BacktestResult",
    "ForecastHorizon",
    "ModelType",
    "PriceForecast",
    "RegimeResult",
    "RelativeValueSignal",
    "Signal",
    "SignalDirection",
    "SignalStatus",
    "SignalType",
    "ImpactAnalysis",
    "ImpactCategory",
    "ImpactEdge",
    "AgentForecast",
    "AgentAlphaScore",
    "ConsensusWeight",
    "ConsensusView",
    "ScenarioFactorType",
    "ScenarioVariable",
    "ScenarioDefinition",
    "ScenarioRunResult",
    "ScenarioComparison",
    "MemoryType",
    "MemoryRecord",
    "LessonProposalStatus",
    "LessonProposal",
    "ReplayMode",
    "AsOfReplayResult",
    "IntelligenceBrief",
    "EnterpriseDataClassification",
    "EnterpriseDataDomain",
    "EnterpriseConnectorType",
    "EnterpriseSourceStatus",
    "Workspace",
    "EnterpriseDataSource",
    "EnterpriseDataset",
    "EnterpriseEntitlementPrincipalType",
    "EnterpriseDataEntitlement",
]
