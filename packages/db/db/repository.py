from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from schemas import (
    AgentAlphaScore,
    AgentForecast,
    ConsensusView,
    EnterpriseDataEntitlement,
    EnterpriseDataset,
    EnterpriseDataSource,
    EnterpriseOpportunity,
    ImpactAnalysis,
    IntelligenceBrief,
    InvestmentCommitteeDecision,
    LessonProposal,
    MemoryRecord,
    ModelRoutingPolicy,
    PostTradeAnalysis,
    PriceForecast,
    RetentionPolicy,
    RiskCheckResult,
    RiskLimits,
    ScenarioRunResult,
    Signal,
    TimeSeriesObservation,
    TradeIdea,
    Workspace,
)

from .engine import build_engine, build_sessionmaker
from .models import (
    AgentAlphaScoreRow,
    AgentConfigRow,
    AgentForecastRow,
    AgentVersionRow,
    ApprovalRow,
    AuditEventRow,
    Base,
    ChatConversationRow,
    ChatMessageRow,
    CommitteeDecisionRow,
    ConsensusViewRow,
    ContactInquiryRow,
    DataFeedConfigRow,
    DataFeedEventRow,
    DecisionJournalRow,
    EnterpriseDataEntitlementRow,
    EnterpriseDataEventRow,
    EnterpriseDatasetRow,
    EnterpriseDataSourceRow,
    EnterpriseOpportunityRow,
    EnterpriseRecordRow,
    FeatureRow,
    ImpactAnalysisRow,
    IntelligenceBriefRow,
    LessonProposalRow,
    MagicLinkTokenRow,
    MarketObservationRow,
    MemoryRecordRow,
    ModelDefinitionRow,
    ModelRoutingPolicyRow,
    OrganizationFeatureEntitlementRow,
    OrganizationRow,
    PermissionRow,
    PostTradeAnalysisRow,
    RetentionPolicyRow,
    RiskCheckRow,
    RiskLimitsRow,
    RoleFeatureEntitlementRow,
    RolePermissionRow,
    RoleRow,
    ScenarioRunRow,
    SessionRow,
    SignalBaselineRow,
    SignalRow,
    SystemSettingHistoryRow,
    SystemSettingRow,
    TradeIdeaRow,
    UserFeatureOverrideRow,
    UserRow,
    WorkspaceMemberRow,
    WorkspaceRow,
)

# The 8 fixed roles from docs/access-model.md §5 (spec §23). Roles are DB rows (not a
# hardcoded enum) so custom roles remain structurally possible, but only these 8 are
# ever seeded.
_ROLE_NAMES = [
    "SUPER_ADMIN",
    "ADMIN",
    "TRADER",
    "RISK_MANAGER",
    "RESEARCHER",
    "EXECUTIVE",
    "VIEWER",
    "API_USER",
]

# The full permission-key list from docs/access-model.md §5 (spec §23), verbatim.
_PERMISSION_KEYS = [
    "dashboard.view",
    "market_data.view",
    "weather.view",
    "storage.view",
    "pipeline.view",
    "lng.view",
    "power.view",
    "news.view",
    "trading_recommendations.view",
    "trading_recommendations.challenge",
    "chief_agent.chat",
    "portfolio.view",
    "portfolio.manage",
    "risk.view",
    "risk.manage",
    "paper_trading.view",
    "paper_trading.execute",
    "data_export",
    "api_access",
    "admin.dashboard",
    "admin.users.view",
    "admin.users.create",
    "admin.users.edit",
    "admin.users.suspend",
    "admin.users.revoke",
    "admin.users.permissions",
    "admin.users.features",
    "admin.users.sessions",
    "admin.organizations",
    "admin.data_feeds",
    "admin.workspaces",
    "admin.enterprise_data",
    "admin.model_routing_policy",
    "admin.retention_policy",
    "admin.system_settings",
    "admin.agent_management",
    "admin.agent_optimization",
    "admin.model_management",
    "admin.audit_logs",
    "admin.feature_management",
    "admin.risk_settings",
    "alpha_signals.view",
    "alpha_impacts.view",
    "alpha_consensus.view",
    "alpha_scenarios.view",
    "alpha_scenarios.run",
    "alpha_memory.view",
    "alpha_memory.review",
    "alpha_replay.view",
    "alpha_brief.view",
    "enterprise_data.query",
    "enterprise_opportunities.view",
    "enterprise_opportunities.generate",
    "enterprise_opportunities.review",
    "enterprise_trading.generate",
]

# Permissions reserved for SUPER_ADMIN: the system-level/risk/model/agent-optimization
# controls the spec keeps behind the strictest boundary (docs/risk-framework.md — the
# Risk Governor and agent-optimization approval chain are never reachable by a lesser
# role). ADMIN gets every other permission, including day-to-day user/org/feature/
# data-feed/agent administration.
_SUPER_ADMIN_ONLY_PERMISSIONS = {
    "admin.system_settings",
    "admin.risk_settings",
    "admin.agent_optimization",
    "admin.model_management",
}

# Default role -> permission grants seeded at startup. This is the initial, reviewable
# default (docs/access-model.md §5); full entitlement enforcement (require_permission
# dependencies, Feature/*Entitlement tables) lands in Milestone 4, at which point this
# mapping becomes admin-editable rather than a fixed seed.
_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "SUPER_ADMIN": list(_PERMISSION_KEYS),
    "ADMIN": [p for p in _PERMISSION_KEYS if p not in _SUPER_ADMIN_ONLY_PERMISSIONS],
    "TRADER": [
        "dashboard.view",
        "market_data.view",
        "weather.view",
        "storage.view",
        "pipeline.view",
        "lng.view",
        "power.view",
        "news.view",
        "trading_recommendations.view",
        "alpha_signals.view",
        "alpha_impacts.view",
        "alpha_consensus.view",
        "alpha_scenarios.view",
        "alpha_scenarios.run",
        "alpha_memory.view",
        "alpha_replay.view",
        "alpha_brief.view",
        "enterprise_data.query",
        "enterprise_opportunities.view",
        "enterprise_opportunities.generate",
        "enterprise_trading.generate",
        "trading_recommendations.challenge",
        "chief_agent.chat",
        "portfolio.view",
        "portfolio.manage",
        "paper_trading.view",
        "paper_trading.execute",
    ],
    "RISK_MANAGER": [
        "dashboard.view",
        "market_data.view",
        "weather.view",
        "storage.view",
        "pipeline.view",
        "lng.view",
        "power.view",
        "news.view",
        "trading_recommendations.view",
        "alpha_signals.view",
        "alpha_impacts.view",
        "alpha_consensus.view",
        "alpha_scenarios.view",
        "alpha_scenarios.run",
        "alpha_memory.view",
        "alpha_memory.review",
        "alpha_replay.view",
        "alpha_brief.view",
        "enterprise_data.query",
        "enterprise_opportunities.view",
        "enterprise_opportunities.review",
        "chief_agent.chat",
        "portfolio.view",
        "risk.view",
        "risk.manage",
        "paper_trading.view",
    ],
    "RESEARCHER": [
        "dashboard.view",
        "market_data.view",
        "weather.view",
        "storage.view",
        "pipeline.view",
        "lng.view",
        "power.view",
        "news.view",
        "trading_recommendations.view",
        "alpha_signals.view",
        "alpha_impacts.view",
        "alpha_consensus.view",
        "alpha_scenarios.view",
        "alpha_scenarios.run",
        "alpha_memory.view",
        "alpha_memory.review",
        "alpha_replay.view",
        "alpha_brief.view",
        "enterprise_data.query",
        "enterprise_opportunities.view",
        "enterprise_opportunities.review",
        "trading_recommendations.challenge",
        "chief_agent.chat",
        "portfolio.view",
        "risk.view",
        "data_export",
    ],
    "EXECUTIVE": [
        "dashboard.view",
        "market_data.view",
        "weather.view",
        "storage.view",
        "pipeline.view",
        "lng.view",
        "power.view",
        "news.view",
        "trading_recommendations.view",
        "alpha_signals.view",
        "alpha_impacts.view",
        "alpha_consensus.view",
        "alpha_scenarios.view",
        "alpha_scenarios.run",
        "alpha_memory.view",
        "alpha_replay.view",
        "alpha_brief.view",
        "enterprise_data.query",
        "enterprise_opportunities.view",
        "portfolio.view",
        "risk.view",
        "chief_agent.chat",
    ],
    "VIEWER": [
        "dashboard.view",
        "market_data.view",
        "weather.view",
        "storage.view",
        "pipeline.view",
        "lng.view",
        "power.view",
        "news.view",
        "trading_recommendations.view",
        "alpha_signals.view",
        "alpha_impacts.view",
        "alpha_consensus.view",
    ],
    "API_USER": [
        "market_data.view",
        "weather.view",
        "storage.view",
        "pipeline.view",
        "lng.view",
        "power.view",
        "news.view",
        "data_export",
        "api_access",
    ],
}

# Feature catalog from docs/access-model.md §5 (spec §24), verbatim. Each entry is
# (key, display name, security_sensitive) — a `security_sensitive` feature gets
# deny-only user-level overrides (see `apps/api/api_app/entitlements.py`).
_FEATURES: list[tuple[str, str, bool]] = [
    ("market_dashboard", "Market Dashboard", False),
    ("ng_fundamentals", "Natural Gas Fundamentals", False),
    ("weather_intelligence", "Weather Intelligence", False),
    ("storage_forecast", "Storage Forecast", False),
    ("pipeline_intelligence", "Pipeline Intelligence", False),
    ("lng_intelligence", "LNG Intelligence", False),
    ("power_market_intelligence", "Power Market Intelligence", False),
    ("news_intelligence", "News Intelligence", False),
    ("ai_trade_recommendations", "AI Trade Recommendations", False),
    ("alpha_intelligence", "Alpha Intelligence", False),
    ("chief_trading_agent_chat", "Chief Trading Agent Chat", True),
    ("portfolio_analytics", "Portfolio Analytics", True),
    ("risk_analytics", "Risk Analytics", True),
    ("ng_digital_twin", "Natural Gas Digital Twin", False),
    ("historical_research", "Historical Research", False),
    ("data_export", "Data Export", True),
    ("api_access", "API Access", True),
    ("paper_trading", "Paper Trading", True),
    ("experimental_features", "Experimental Features", True),
]

# Default role -> feature grants, mirroring _ROLE_PERMISSIONS' capability shape.
# Role-level feature access is deny-by-default: a role only has a feature if it's
# listed here (see `RoleFeatureEntitlementRow`'s docstring).
_ROLE_FEATURES: dict[str, list[str]] = {
    "SUPER_ADMIN": [key for key, _, _ in _FEATURES],
    "ADMIN": [key for key, _, _ in _FEATURES],
    "TRADER": [
        "market_dashboard",
        "ng_fundamentals",
        "weather_intelligence",
        "storage_forecast",
        "pipeline_intelligence",
        "lng_intelligence",
        "power_market_intelligence",
        "news_intelligence",
        "ai_trade_recommendations",
        "alpha_intelligence",
        "chief_trading_agent_chat",
        "portfolio_analytics",
        "ng_digital_twin",
        "paper_trading",
    ],
    "RISK_MANAGER": [
        "market_dashboard",
        "ng_fundamentals",
        "weather_intelligence",
        "storage_forecast",
        "pipeline_intelligence",
        "lng_intelligence",
        "power_market_intelligence",
        "news_intelligence",
        "ai_trade_recommendations",
        "alpha_intelligence",
        "chief_trading_agent_chat",
        "portfolio_analytics",
        "risk_analytics",
        "ng_digital_twin",
    ],
    "RESEARCHER": [
        "market_dashboard",
        "ng_fundamentals",
        "weather_intelligence",
        "storage_forecast",
        "pipeline_intelligence",
        "lng_intelligence",
        "power_market_intelligence",
        "news_intelligence",
        "ai_trade_recommendations",
        "alpha_intelligence",
        "chief_trading_agent_chat",
        "ng_digital_twin",
        "historical_research",
        "data_export",
    ],
    "EXECUTIVE": [
        "market_dashboard",
        "ng_fundamentals",
        "weather_intelligence",
        "storage_forecast",
        "pipeline_intelligence",
        "lng_intelligence",
        "power_market_intelligence",
        "news_intelligence",
        "ai_trade_recommendations",
        "alpha_intelligence",
        "chief_trading_agent_chat",
        "portfolio_analytics",
        "risk_analytics",
        "ng_digital_twin",
    ],
    "VIEWER": [
        "market_dashboard",
        "ng_fundamentals",
        "weather_intelligence",
        "storage_forecast",
        "pipeline_intelligence",
        "lng_intelligence",
        "power_market_intelligence",
        "news_intelligence",
        "ng_digital_twin",
    ],
    "API_USER": [
        "market_dashboard",
        "ng_fundamentals",
        "weather_intelligence",
        "storage_forecast",
        "pipeline_intelligence",
        "lng_intelligence",
        "power_market_intelligence",
        "news_intelligence",
        "data_export",
        "api_access",
    ],
}


# System settings catalog (spec §38), seeded once at first boot. Each value is
# already JSON-shaped (a plain string for most, a dict for the handful of
# structured ones) since `SystemSettingRow.value` is a JSON column.
_SYSTEM_SETTINGS_DEFAULTS: dict[str, object] = {
    "platform_name": "AlphaGasIQ",
    "platform_description": "Agentic natural gas intelligence & paper-trading platform.",
    "market_coverage": "North America",
    "supported_commodities": ["Henry Hub Natural Gas"],
    "system_status_message": "",
    "maintenance_message": "",
    "support_email": "support@alphagasiq.local",
    "contact_information": "",
    "legal_disclaimer": "AlphaGasIQ is a decision-support platform. Nothing herein is investment advice.",
    "trading_disclaimer": "All trading on this platform is simulated (paper trading only).",
    "default_timezone": "America/New_York",
    "default_currency": "USD",
    "default_units": "Bcf/d",
    "default_market": "HENRY_HUB",
    "default_dashboard": "market",
    "data_freshness_policies": {},
    "alert_thresholds": {},
    "notification_settings": {},
    "feature_defaults": {},
    "chat_defaults": {},
}

# Legal `AgentVersionRow.status` transitions (spec §41) -- no step may be skipped, so a
# prompt/model change can never automatically reach PRODUCTION without passing through
# TESTING and APPROVED first. TESTING -> DRAFT lets a reviewer send a version back for
# rework rather than only forward or discard.
_AGENT_VERSION_TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"TESTING", "RETIRED"},
    "TESTING": {"APPROVED", "DRAFT", "RETIRED"},
    "APPROVED": {"PRODUCTION", "RETIRED"},
    "PRODUCTION": {"RETIRED", "ROLLED_BACK"},
    "RETIRED": set(),
    "ROLLED_BACK": set(),
}


def _organization_to_dict(row: OrganizationRow) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "website": row.website,
        "industry": row.industry,
        "company_type": row.company_type,
        "country": row.country,
        "state_region": row.state_region,
        "status": row.status,
        "billing_plan": row.billing_plan,
        "account_owner": row.account_owner,
        "primary_contact": row.primary_contact,
        "feature_package": row.feature_package,
        "data_entitlements": row.data_entitlements,
        "notes": row.notes,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _role_to_dict(row: RoleRow) -> dict:
    return {"id": row.id, "name": row.name, "description": row.description}


def _data_feed_config_to_dict(row: DataFeedConfigRow) -> dict:
    return {
        "provider_id": row.provider_id,
        "enabled": row.enabled,
        "paused": row.paused,
        "polling_frequency_seconds": row.polling_frequency_seconds,
        "freshness_threshold_seconds": row.freshness_threshold_seconds,
        "priority": row.priority,
        "fallback_provider_id": row.fallback_provider_id,
        "notes": row.notes,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at,
    }


def _data_feed_event_to_dict(row: DataFeedEventRow) -> dict:
    return {
        "id": row.id,
        "provider_id": row.provider_id,
        "event_type": row.event_type,
        "status": row.status,
        "detail": row.detail,
        "records_received": row.records_received,
        "latency_ms": row.latency_ms,
        "occurred_at": row.occurred_at,
    }


def _agent_config_to_dict(row: AgentConfigRow) -> dict:
    return {
        "agent_type": row.agent_type,
        "status": row.status,
        "confidence_threshold": row.confidence_threshold,
        "alert_threshold": row.alert_threshold,
        "escalation_threshold": row.escalation_threshold,
        "notes": row.notes,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at,
    }


def _agent_version_to_dict(row: AgentVersionRow) -> dict:
    return {
        "id": row.id,
        "agent_type": row.agent_type,
        "version": row.version,
        "model_provider": row.model_provider,
        "model_name": row.model_name,
        "system_instructions": row.system_instructions,
        "tool_configuration": row.tool_configuration,
        "data_sources": row.data_sources,
        "execution_settings": row.execution_settings,
        "thresholds": row.thresholds,
        "status": row.status,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "evaluation_results": row.evaluation_results,
        "approved_by": row.approved_by,
        "approved_at": row.approved_at,
        "deployment_timestamp": row.deployment_timestamp,
        "notes": row.notes,
    }


def _model_definition_to_dict(row: ModelDefinitionRow) -> dict:
    return {
        "id": row.id,
        "provider": row.provider,
        "model_name": row.model_name,
        "version": row.version,
        "purpose": row.purpose,
        "approved_agent_types": row.approved_agent_types,
        "status": row.status,
        "context_window": row.context_window,
        "cost_per_1k_input_tokens": row.cost_per_1k_input_tokens,
        "cost_per_1k_output_tokens": row.cost_per_1k_output_tokens,
        "notes": row.notes,
        "created_at": row.created_at,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at,
        "approved_at": row.approved_at,
    }


def _signal_row_to_dict(row: SignalRow) -> dict:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "workspace_id": row.workspace_id,
        "signal_type": row.signal_type,
        "category": row.category,
        "subcategory": row.subcategory,
        "source_ids": row.source_ids,
        "detected_at": row.detected_at,
        "effective_at": row.effective_at,
        "market": row.market,
        "geography": row.geography,
        "asset_ids": row.asset_ids,
        "headline": row.headline,
        "description": row.description,
        "previous_value": row.previous_value,
        "current_value": row.current_value,
        "absolute_change": row.absolute_change,
        "percent_change": row.percent_change,
        "z_score": row.z_score,
        "historical_percentile": row.historical_percentile,
        "materiality_score": row.materiality_score,
        "novelty_score": row.novelty_score,
        "confidence": row.confidence,
        "direction": row.direction,
        "time_horizon": row.time_horizon,
        "data_quality": row.data_quality,
        "citations": row.citations,
        "affected_agents": row.affected_agents,
        "affected_business_functions": row.affected_business_functions,
        "status": row.status,
        "created_at": row.created_at,
    }


def _impact_analysis_row_to_dict(row: ImpactAnalysisRow) -> dict:
    return {
        "id": row.id,
        "signal_id": row.signal_id,
        "organization_id": row.organization_id,
        "event_type": row.event_type,
        "physical_impact": row.physical_impact,
        "supply_impact_bcf_day": row.supply_impact_bcf_day,
        "demand_impact_bcf_day": row.demand_impact_bcf_day,
        "storage_impact_bcf": row.storage_impact_bcf,
        "expected_duration": row.expected_duration,
        "affected_geographies": row.affected_geographies,
        "affected_assets": row.affected_assets,
        "affected_markets": row.affected_markets,
        "affected_contracts": row.affected_contracts,
        "basis_implications": row.basis_implications,
        "curve_implications": row.curve_implications,
        "volatility_implications": row.volatility_implications,
        "portfolio_implications": row.portfolio_implications,
        "risk_implications": row.risk_implications,
        "bullish_bearish": row.bullish_bearish,
        "magnitude": row.magnitude,
        "confidence": row.confidence,
        "assumptions": row.assumptions,
        "uncertainties": row.uncertainties,
        "alternative_interpretations": row.alternative_interpretations,
        "data_sources": row.data_sources,
        "agent_contributors": row.agent_contributors,
        "chain": row.chain,
        "created_at": row.created_at,
    }


def _agent_forecast_row_to_dict(row: AgentForecastRow) -> dict:
    return {
        "id": row.id,
        "agent_id": row.agent_id,
        "agent_type": row.agent_type,
        "agent_version": row.agent_version,
        "organization_id": row.organization_id,
        "forecast_type": row.forecast_type,
        "target": row.target,
        "market": row.market,
        "horizon": row.horizon,
        "forecast_value": row.forecast_value,
        "direction": row.direction,
        "probability": row.probability,
        "confidence": row.confidence,
        "drivers": row.drivers,
        "citations": row.citations,
        "created_at": row.created_at,
        "expires_at": row.expires_at,
    }


def _agent_alpha_score_row_to_dict(row: AgentAlphaScoreRow) -> dict:
    return {
        "agent_type": row.agent_type,
        "score": row.score,
        "method": row.method,
        "sample_size": row.sample_size,
        "components": row.components,
        "computed_at": row.computed_at,
    }


def _consensus_view_row_to_dict(row: ConsensusViewRow) -> dict:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "consensus_type": row.consensus_type,
        "market": row.market,
        "target": row.target,
        "horizon": row.horizon,
        "consensus_value": row.consensus_value,
        "bull_probability": row.bull_probability,
        "bear_probability": row.bear_probability,
        "neutral_probability": row.neutral_probability,
        "confidence": row.confidence,
        "dispersion": row.dispersion,
        "agreement_label": row.agreement_label,
        "agent_count": row.agent_count,
        "agent_weights": row.agent_weights,
        "leading_agents": row.leading_agents,
        "dissenting_agents": row.dissenting_agents,
        "drivers": row.drivers,
        "risks": row.risks,
        "market_consensus_value": row.market_consensus_value,
        "variance_vs_market": row.variance_vs_market,
        "created_at": row.created_at,
    }


def _scenario_run_row_to_dict(row: ScenarioRunRow) -> dict:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "scenario_name": row.scenario_name,
        "scenario_description": row.scenario_description,
        "base_scenario_ids": row.base_scenario_ids,
        "price_shock_pct": row.price_shock_pct,
        "demand_shock_bcf_d": row.demand_shock_bcf_d,
        "supply_shock_bcf_d": row.supply_shock_bcf_d,
        "volatility_multiplier": row.volatility_multiplier,
        "portfolio_pnl": row.portfolio_pnl,
        "strategy_pnl": row.strategy_pnl,
        "margin_impact": row.margin_impact,
        "var_impact": row.var_impact,
        "largest_risk_contributor": row.largest_risk_contributor,
        "requested_by": row.requested_by,
        "run_at": row.run_at,
    }


def _memory_record_row_to_dict(row: MemoryRecordRow) -> dict:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "memory_type": row.memory_type,
        "trade_id": row.trade_id,
        "market": row.market,
        "strategy": row.strategy,
        "title": row.title,
        "summary": row.summary,
        "outcome_quadrant": row.outcome_quadrant,
        "structured_context": row.structured_context,
        "tags": row.tags,
        "created_at": row.created_at,
    }


def _lesson_proposal_row_to_dict(row: LessonProposalRow) -> dict:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "memory_record_id": row.memory_record_id,
        "proposed_lesson": row.proposed_lesson,
        "rationale": row.rationale,
        "status": row.status,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": row.reviewed_at,
        "created_at": row.created_at,
    }


def _market_observation_row_to_dict(row: MarketObservationRow) -> dict:
    return {
        "id": row.id,
        "source": row.source,
        "source_type": row.source_type,
        "series_id": row.series_id,
        "symbol": row.symbol,
        "commodity": row.commodity,
        "category": row.category,
        "sub_category": row.sub_category,
        "geography": row.geography,
        "location": row.location,
        "value": row.value,
        "unit": row.unit,
        "observation_time": row.observation_time,
        "publication_time": row.publication_time,
        "revision_number": row.revision_number,
        "quality_score": row.quality_score,
        "confidence": row.confidence,
        "metadata": row.metadata_,
        "lineage": row.lineage,
        "revision_time": row.revision_time,
        "valid_from": row.valid_from,
        "valid_to": row.valid_to,
        "received_time": row.received_time,
        "created_at": row.created_at,
    }


def _intelligence_brief_row_to_dict(row: IntelligenceBriefRow) -> dict:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "market": row.market,
        "period_start": row.period_start,
        "period_end": row.period_end,
        "headline": row.headline,
        "summary": row.summary,
        "top_signals": row.top_signals,
        "top_impacts": row.top_impacts,
        "consensus_highlights": row.consensus_highlights,
        "notable_scenario_runs": row.notable_scenario_runs,
        "pending_lessons": row.pending_lessons,
        "generated_at": row.generated_at,
    }


def _model_routing_policy_row_to_dict(row: ModelRoutingPolicyRow) -> dict:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "data_classification": row.data_classification,
        "allow_external_llm_processing": row.allow_external_llm_processing,
        "allowed_provider": row.allowed_provider,
        "allowed_region": row.allowed_region,
        "logging_allowed": row.logging_allowed,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _enterprise_opportunity_row_to_dict(row: EnterpriseOpportunityRow) -> dict:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "workspace_id": row.workspace_id,
        "opportunity_type": row.opportunity_type,
        "market": row.market,
        "title": row.title,
        "summary": row.summary,
        "confidence": row.confidence,
        "supporting_signal_ids": row.supporting_signal_ids,
        "supporting_consensus_id": row.supporting_consensus_id,
        "related_dataset_id": row.related_dataset_id,
        "related_record_id": row.related_record_id,
        "status": row.status,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": row.reviewed_at,
        "created_at": row.created_at,
    }


def _retention_policy_row_to_dict(row: RetentionPolicyRow) -> dict:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "data_classification": row.data_classification,
        "retention_days": row.retention_days,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _workspace_row_to_dict(row: WorkspaceRow) -> dict:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "name": row.name,
        "description": row.description,
        "created_by": row.created_by,
        "created_at": row.created_at,
    }


def _enterprise_data_source_row_to_dict(row: EnterpriseDataSourceRow) -> dict:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "workspace_id": row.workspace_id,
        "name": row.name,
        "connector_type": row.connector_type,
        "classification": row.classification,
        "status": row.status,
        "description": row.description,
        "connection_config": row.connection_config,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _enterprise_dataset_row_to_dict(row: EnterpriseDatasetRow) -> dict:
    return {
        "id": row.id,
        "source_id": row.source_id,
        "organization_id": row.organization_id,
        "name": row.name,
        "domain": row.domain,
        "classification": row.classification,
        "schema_summary": row.schema_summary,
        "row_count": row.row_count,
        "last_synced_at": row.last_synced_at,
        "created_at": row.created_at,
    }


def _enterprise_data_entitlement_row_to_dict(row: EnterpriseDataEntitlementRow) -> dict:
    return {
        "id": row.id,
        "dataset_id": row.dataset_id,
        "principal_type": row.principal_type,
        "principal_id": row.principal_id,
        "granted_by": row.granted_by,
        "granted_at": row.granted_at,
    }


def _enterprise_record_row_to_dict(row: EnterpriseRecordRow) -> dict:
    return {
        "id": row.id,
        "dataset_id": row.dataset_id,
        "row_data": row.row_data,
        "ingested_at": row.ingested_at,
    }


def _enterprise_data_event_row_to_dict(row: EnterpriseDataEventRow) -> dict:
    return {
        "id": row.id,
        "source_id": row.source_id,
        "event_type": row.event_type,
        "status": row.status,
        "detail": row.detail,
        "rows_ingested": row.rows_ingested,
        "rows_rejected": row.rows_rejected,
        "latency_ms": row.latency_ms,
        "occurred_at": row.occurred_at,
    }


def _audit_event_to_dict(row: AuditEventRow) -> dict:
    return {
        "id": row.id,
        "actor_user_id": row.actor_user_id,
        "action": row.action,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "before": row.before,
        "after": row.after,
        "reason": row.reason,
        "occurred_at": row.occurred_at,
    }


def _system_setting_to_dict(row: SystemSettingRow) -> dict:
    return {
        "key": row.key,
        "value": row.value,
        "version": row.version,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at,
    }


def _user_to_dict(row: UserRow) -> dict:
    return {
        "id": row.id,
        "first_name": row.first_name,
        "last_name": row.last_name,
        "email": row.email,
        "organization_id": row.organization_id,
        "job_title": row.job_title,
        "department": row.department,
        "phone": row.phone,
        "country": row.country,
        "state_region": row.state_region,
        "primary_use_case": row.primary_use_case,
        "market_experience": row.market_experience,
        "role_id": row.role_id,
        "status": row.status,
        "expiration_at": row.expiration_at,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "activated_at": row.activated_at,
        "last_login_at": row.last_login_at,
    }


def _magic_link_token_to_dict(row: MagicLinkTokenRow) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "token_hash": row.token_hash,
        "purpose": row.purpose,
        "created_at": row.created_at,
        "expires_at": row.expires_at,
        "consumed_at": row.consumed_at,
        "revoked_at": row.revoked_at,
        "requested_ip": row.requested_ip,
        "user_agent": row.user_agent,
    }


def _session_to_dict(row: SessionRow) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "created_at": row.created_at,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
        "ip_address": row.ip_address,
        "user_agent": row.user_agent,
        "last_seen_at": row.last_seen_at,
    }


def _naive_utc(dt: datetime | None) -> datetime | None:
    """Normalizes to a naive UTC `datetime` before binding to a `DateTime` column.

    The schemas across this codebase mix naive (`datetime.utcnow()` defaults) and
    timezone-aware datetimes for what's conceptually the same "naive UTC" convention.
    sqlite silently tolerates that mix; `asyncpg`'s timestamp encoder does not — it
    raises `TypeError: can't subtract offset-naive and offset-aware datetimes` when an
    aware value reaches a `TIMESTAMP WITHOUT TIME ZONE` column, which real-Postgres
    validation of this repository surfaced.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class SqlAppRepository:
    """Durable, write-through persistence for `AppState`'s trading objects.

    `AppState` keeps its existing in-memory dicts as the router-facing read path (so
    no router code changes are needed); every mutation additionally writes through to
    this repository, and `hydrate()` reloads everything from the DB on boot so state
    survives a process restart. Deliberately decoupled from `apps/api` — it only knows
    about `schemas` types (safe: `packages/db` already depends on `alphagasiq-schemas`)
    plus plain primitives for the one app-local type (`Approval`), so `apps/api` maps
    to/from its own model at the call site instead of this package importing it.
    """

    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = build_engine(database_url)
        self.session_factory: async_sessionmaker = build_sessionmaker(self.engine)

    async def init_schema(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def seed_rbac_defaults(self) -> None:
        """Seeds the 8 fixed roles, the full permission-key list, and each role's
        default grants (see the module-level `_ROLE_NAMES`/`_PERMISSION_KEYS`/
        `_ROLE_PERMISSIONS` constants above). Idempotent — safe to call on every
        process boot; only inserts rows that don't already exist, so an admin who
        edits a role's grants in a later milestone won't have that edit reverted by
        the next restart re-running this seed."""
        async with self.session_factory() as session:
            existing_role_names = set((await session.execute(select(RoleRow.name))).scalars().all())
            for name in _ROLE_NAMES:
                if name not in existing_role_names:
                    session.add(RoleRow(name=name))

            existing_permission_keys = set((await session.execute(select(PermissionRow.key))).scalars().all())
            for key in _PERMISSION_KEYS:
                if key not in existing_permission_keys:
                    session.add(PermissionRow(key=key))

            await session.flush()

            role_id_by_name = {r.name: r.id for r in (await session.execute(select(RoleRow))).scalars().all()}
            permission_id_by_key = {
                p.key: p.id for p in (await session.execute(select(PermissionRow))).scalars().all()
            }
            existing_grants = {
                (rp.role_id, rp.permission_id)
                for rp in (await session.execute(select(RolePermissionRow))).scalars().all()
            }

            for role_name, permission_keys in _ROLE_PERMISSIONS.items():
                role_id = role_id_by_name[role_name]
                for key in permission_keys:
                    permission_id = permission_id_by_key[key]
                    if (role_id, permission_id) not in existing_grants:
                        session.add(RolePermissionRow(role_id=role_id, permission_id=permission_id))

            await session.commit()

    async def get_permission_keys_for_role(self, role_name: str) -> set[str]:
        """The effective permission set for one DB role — used by
        `apps/api/api_app/entitlements.py::get_effective_permissions`."""
        async with self.session_factory() as session:
            role = (await session.execute(select(RoleRow).where(RoleRow.name == role_name))).scalar_one_or_none()
            if role is None:
                return set()
            keys = (
                await session.execute(
                    select(PermissionRow.key)
                    .join(RolePermissionRow, RolePermissionRow.permission_id == PermissionRow.id)
                    .where(RolePermissionRow.role_id == role.id)
                )
            ).scalars().all()
        return set(keys)

    async def seed_feature_defaults(self) -> None:
        """Seeds the feature catalog and each role's default feature grants (module-
        level `_FEATURES`/`_ROLE_FEATURES` above) — the Milestone 4 counterpart to
        `seed_rbac_defaults`. Idempotent for the same reason: safe on every boot,
        never reverts an admin's later edit to an existing grant."""
        async with self.session_factory() as session:
            existing_feature_keys = set((await session.execute(select(FeatureRow.key))).scalars().all())
            for key, name, security_sensitive in _FEATURES:
                if key not in existing_feature_keys:
                    session.add(FeatureRow(key=key, name=name, security_sensitive=security_sensitive))
            await session.flush()

            role_id_by_name = {r.name: r.id for r in (await session.execute(select(RoleRow))).scalars().all()}
            feature_id_by_key = {f.key: f.id for f in (await session.execute(select(FeatureRow))).scalars().all()}
            existing_grants = {
                (rfe.role_id, rfe.feature_id)
                for rfe in (await session.execute(select(RoleFeatureEntitlementRow))).scalars().all()
            }

            for role_name, feature_keys in _ROLE_FEATURES.items():
                role_id = role_id_by_name.get(role_name)
                if role_id is None:
                    continue
                for key in feature_keys:
                    feature_id = feature_id_by_key[key]
                    if (role_id, feature_id) not in existing_grants:
                        session.add(RoleFeatureEntitlementRow(role_id=role_id, feature_id=feature_id, enabled=True))

            await session.commit()

    async def list_features(self) -> list[dict]:
        async with self.session_factory() as session:
            rows = (await session.execute(select(FeatureRow).order_by(FeatureRow.key))).scalars().all()
        return [
            {
                "id": r.id,
                "key": r.key,
                "name": r.name,
                "description": r.description,
                "security_sensitive": r.security_sensitive,
                "globally_enabled": r.globally_enabled,
            }
            for r in rows
        ]

    async def get_role_feature_keys(self, role_id: str) -> set[str]:
        """The set of feature keys a role explicitly grants (enabled=True rows only —
        role-level access is deny-by-default)."""
        async with self.session_factory() as session:
            keys = (
                await session.execute(
                    select(FeatureRow.key)
                    .join(RoleFeatureEntitlementRow, RoleFeatureEntitlementRow.feature_id == FeatureRow.id)
                    .where(RoleFeatureEntitlementRow.role_id == role_id, RoleFeatureEntitlementRow.enabled.is_(True))
                )
            ).scalars().all()
        return set(keys)

    async def get_organization_feature_overrides(self, organization_id: str) -> dict[str, bool]:
        """feature_key -> enabled, for every explicit org-level row. Absence of a key
        means the org places no restriction beyond the user's role."""
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(FeatureRow.key, OrganizationFeatureEntitlementRow.enabled)
                    .join(FeatureRow, OrganizationFeatureEntitlementRow.feature_id == FeatureRow.id)
                    .where(OrganizationFeatureEntitlementRow.organization_id == organization_id)
                )
            ).all()
        return {key: enabled for key, enabled in rows}

    async def get_user_feature_overrides(self, user_id: str) -> dict[str, bool]:
        """feature_key -> enabled, for every explicit per-user override row."""
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(FeatureRow.key, UserFeatureOverrideRow.enabled)
                    .join(FeatureRow, UserFeatureOverrideRow.feature_id == FeatureRow.id)
                    .where(UserFeatureOverrideRow.user_id == user_id)
                )
            ).all()
        return {key: enabled for key, enabled in rows}

    async def set_organization_feature_override(self, *, organization_id: str, feature_key: str, enabled: bool) -> None:
        async with self.session_factory() as session:
            feature = (await session.execute(select(FeatureRow).where(FeatureRow.key == feature_key))).scalar_one_or_none()
            if feature is None:
                raise ValueError(f"Unknown feature key: {feature_key}")
            existing = (
                await session.execute(
                    select(OrganizationFeatureEntitlementRow).where(
                        OrganizationFeatureEntitlementRow.organization_id == organization_id,
                        OrganizationFeatureEntitlementRow.feature_id == feature.id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.enabled = enabled
            else:
                session.add(
                    OrganizationFeatureEntitlementRow(organization_id=organization_id, feature_id=feature.id, enabled=enabled)
                )
            await session.commit()

    async def set_user_feature_override(self, *, user_id: str, feature_key: str, enabled: bool) -> None:
        async with self.session_factory() as session:
            feature = (await session.execute(select(FeatureRow).where(FeatureRow.key == feature_key))).scalar_one_or_none()
            if feature is None:
                raise ValueError(f"Unknown feature key: {feature_key}")
            existing = (
                await session.execute(
                    select(UserFeatureOverrideRow).where(
                        UserFeatureOverrideRow.user_id == user_id,
                        UserFeatureOverrideRow.feature_id == feature.id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.enabled = enabled
            else:
                session.add(UserFeatureOverrideRow(user_id=user_id, feature_id=feature.id, enabled=enabled))
            await session.commit()

    async def set_feature_globally_enabled(self, feature_key: str, enabled: bool) -> dict:
        """Milestone 6 "Feature Management" (spec §34) — the global on/off switch a
        `Feature` row's `globally_enabled` column already models; this just exposes
        writing it."""
        async with self.session_factory() as session:
            feature = (await session.execute(select(FeatureRow).where(FeatureRow.key == feature_key))).scalar_one_or_none()
            if feature is None:
                raise ValueError(f"Unknown feature key: {feature_key}")
            feature.globally_enabled = enabled
            await session.commit()
            await session.refresh(feature)
        return {
            "id": feature.id,
            "key": feature.key,
            "name": feature.name,
            "description": feature.description,
            "security_sensitive": feature.security_sensitive,
            "globally_enabled": feature.globally_enabled,
        }

    async def set_role_feature_entitlement(self, *, role_id: str, feature_key: str, enabled: bool) -> None:
        async with self.session_factory() as session:
            feature = (await session.execute(select(FeatureRow).where(FeatureRow.key == feature_key))).scalar_one_or_none()
            if feature is None:
                raise ValueError(f"Unknown feature key: {feature_key}")
            existing = (
                await session.execute(
                    select(RoleFeatureEntitlementRow).where(
                        RoleFeatureEntitlementRow.role_id == role_id,
                        RoleFeatureEntitlementRow.feature_id == feature.id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.enabled = enabled
            else:
                session.add(RoleFeatureEntitlementRow(role_id=role_id, feature_id=feature.id, enabled=enabled))
            await session.commit()

    # -- system settings (spec §38) ----------------------------------------------------

    async def seed_system_settings_defaults(self) -> None:
        """Idempotent: only inserts a key if it doesn't already exist, so an admin's
        prior edit is never reverted by a later restart re-running this seed."""
        async with self.session_factory() as session:
            existing_keys = set((await session.execute(select(SystemSettingRow.key))).scalars().all())
            for key, value in _SYSTEM_SETTINGS_DEFAULTS.items():
                if key not in existing_keys:
                    session.add(SystemSettingRow(key=key, value=value, version=1))
            await session.commit()

    async def list_system_settings(self) -> list[dict]:
        async with self.session_factory() as session:
            rows = (await session.execute(select(SystemSettingRow).order_by(SystemSettingRow.key))).scalars().all()
        return [_system_setting_to_dict(r) for r in rows]

    async def get_system_setting(self, key: str) -> dict | None:
        async with self.session_factory() as session:
            row = (await session.execute(select(SystemSettingRow).where(SystemSettingRow.key == key))).scalar_one_or_none()
        return _system_setting_to_dict(row) if row is not None else None

    async def set_system_setting(self, key: str, value: object, *, updated_by: str | None) -> dict:
        """Writes the new value and appends the row's *previous* state to
        `system_setting_history` first — so history is always "what it used to be,"
        letting an admin see (and manually revert to) any prior version."""
        async with self.session_factory() as session:
            row = (await session.execute(select(SystemSettingRow).where(SystemSettingRow.key == key))).scalar_one_or_none()
            if row is None:
                raise ValueError(f"Unknown system setting key: {key}")
            session.add(
                SystemSettingHistoryRow(
                    key=row.key, value=row.value, version=row.version, changed_by=row.updated_by, changed_at=row.updated_at
                )
            )
            row.value = value
            row.version += 1
            row.updated_by = updated_by
            row.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(row)
        return _system_setting_to_dict(row)

    async def list_system_setting_history(self, key: str) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(SystemSettingHistoryRow)
                        .where(SystemSettingHistoryRow.key == key)
                        .order_by(SystemSettingHistoryRow.version.desc())
                    )
                )
                .scalars()
                .all()
            )
        return [
            {
                "id": r.id,
                "key": r.key,
                "value": r.value,
                "version": r.version,
                "changed_by": r.changed_by,
                "changed_at": r.changed_at,
            }
            for r in rows
        ]

    # -- admin: user profile edits ------------------------------------------------------

    async def update_user_profile(self, user_id: str, **fields) -> dict | None:
        """Milestone 6 "Edit user profile" / "Change organization" / "Change role" /
        "Set account expiration" (spec §32). Only the keys actually passed are
        updated — the caller (the admin API layer) decides which fields a request
        touched; this never overwrites a field with `None` unless `None` was
        explicitly passed for it."""
        async with self.session_factory() as session:
            row = (await session.execute(select(UserRow).where(UserRow.id == user_id))).scalar_one_or_none()
            if row is None:
                return None
            for field, value in fields.items():
                setattr(row, field, value)
            row.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(row)
        return _user_to_dict(row)

    async def update_organization(self, organization_id: str, **fields) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(OrganizationRow).where(OrganizationRow.id == organization_id))
            ).scalar_one_or_none()
            if row is None:
                return None
            for field, value in fields.items():
                setattr(row, field, value)
            row.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(row)
        return _organization_to_dict(row)

    # -- data feed administration (spec §§35-37) ---------------------------------------

    async def seed_data_feed_configs(self, provider_ids: list[str]) -> None:
        """Idempotent: seeds one default config row per currently-registered
        provider id. Safe to re-run on every boot (e.g. after a new connector is
        registered) without touching an admin's prior edits to an existing row."""
        async with self.session_factory() as session:
            existing = set((await session.execute(select(DataFeedConfigRow.provider_id))).scalars().all())
            for provider_id in provider_ids:
                if provider_id not in existing:
                    session.add(DataFeedConfigRow(provider_id=provider_id))
            await session.commit()

    async def list_data_feed_configs(self) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (await session.execute(select(DataFeedConfigRow).order_by(DataFeedConfigRow.provider_id)))
                .scalars()
                .all()
            )
        return [_data_feed_config_to_dict(r) for r in rows]

    async def get_data_feed_config(self, provider_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(DataFeedConfigRow).where(DataFeedConfigRow.provider_id == provider_id))
            ).scalar_one_or_none()
        return _data_feed_config_to_dict(row) if row is not None else None

    async def update_data_feed_config(self, provider_id: str, **fields) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(DataFeedConfigRow).where(DataFeedConfigRow.provider_id == provider_id))
            ).scalar_one_or_none()
            if row is None:
                return None
            for field, value in fields.items():
                setattr(row, field, value)
            row.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(row)
        return _data_feed_config_to_dict(row)

    async def record_data_feed_event(
        self,
        *,
        provider_id: str,
        event_type: str,
        status: str,
        detail: str = "",
        records_received: int | None = None,
        latency_ms: float | None = None,
    ) -> dict:
        row = DataFeedEventRow(
            provider_id=provider_id,
            event_type=event_type,
            status=status,
            detail=detail,
            records_received=records_received,
            latency_ms=latency_ms,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return _data_feed_event_to_dict(row)

    async def list_data_feed_events(self, provider_id: str, *, limit: int = 50) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(DataFeedEventRow)
                        .where(DataFeedEventRow.provider_id == provider_id)
                        .order_by(DataFeedEventRow.occurred_at.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [_data_feed_event_to_dict(r) for r in rows]

    # -- agent administration (spec §39) -------------------------------------------------

    async def seed_agent_configs(self, agent_types: list[str]) -> None:
        """Idempotent: seeds one default config row per currently-implemented,
        administrable agent type. Safe to re-run on every boot without touching an
        admin's prior edits to an existing row."""
        async with self.session_factory() as session:
            existing = set((await session.execute(select(AgentConfigRow.agent_type))).scalars().all())
            for agent_type in agent_types:
                if agent_type not in existing:
                    session.add(AgentConfigRow(agent_type=agent_type))
            await session.commit()

    async def list_agent_configs(self) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (await session.execute(select(AgentConfigRow).order_by(AgentConfigRow.agent_type)))
                .scalars()
                .all()
            )
        return [_agent_config_to_dict(r) for r in rows]

    async def get_agent_config(self, agent_type: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(AgentConfigRow).where(AgentConfigRow.agent_type == agent_type))
            ).scalar_one_or_none()
        return _agent_config_to_dict(row) if row is not None else None

    async def update_agent_config(self, agent_type: str, **fields) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(AgentConfigRow).where(AgentConfigRow.agent_type == agent_type))
            ).scalar_one_or_none()
            if row is None:
                return None
            for field, value in fields.items():
                setattr(row, field, value)
            row.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(row)
        return _agent_config_to_dict(row)

    # -- agent versioning (spec §§40-41) -------------------------------------------------

    async def create_agent_version(
        self,
        *,
        agent_type: str,
        version: str,
        model_provider: str | None = None,
        model_name: str | None = None,
        system_instructions: str | None = None,
        tool_configuration: dict | None = None,
        data_sources: list | None = None,
        execution_settings: dict | None = None,
        thresholds: dict | None = None,
        created_by: str | None = None,
        notes: str | None = None,
    ) -> dict:
        """Always creates a new `DRAFT` row -- an agent's approved configuration is
        never edited in place (spec §41)."""
        row = AgentVersionRow(
            agent_type=agent_type,
            version=version,
            model_provider=model_provider,
            model_name=model_name,
            system_instructions=system_instructions,
            tool_configuration=tool_configuration or {},
            data_sources=data_sources or [],
            execution_settings=execution_settings or {},
            thresholds=thresholds or {},
            created_by=created_by,
            notes=notes,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return _agent_version_to_dict(row)

    async def list_agent_versions(self, agent_type: str) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(AgentVersionRow)
                        .where(AgentVersionRow.agent_type == agent_type)
                        .order_by(AgentVersionRow.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
        return [_agent_version_to_dict(r) for r in rows]

    async def get_agent_version(self, version_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(AgentVersionRow).where(AgentVersionRow.id == version_id))
            ).scalar_one_or_none()
        return _agent_version_to_dict(row) if row is not None else None

    async def get_production_agent_version(self, agent_type: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(AgentVersionRow).where(
                        AgentVersionRow.agent_type == agent_type, AgentVersionRow.status == "PRODUCTION"
                    )
                )
            ).scalar_one_or_none()
        return _agent_version_to_dict(row) if row is not None else None

    async def transition_agent_version_status(
        self,
        version_id: str,
        new_status: str,
        *,
        actor: str | None = None,
        evaluation_results: dict | None = None,
    ) -> dict | None:
        """Enforces the fixed DRAFT -> TESTING -> APPROVED -> PRODUCTION -> (RETIRED |
        ROLLED_BACK) lifecycle (spec §41) -- raises `ValueError` on an illegal jump so
        no step can be skipped. Promoting to `PRODUCTION` automatically retires the
        agent_type's prior `PRODUCTION` row, if any, so at most one exists at a time.
        Also enforces spec §43's "an agent may never be configured to use a model that
        isn't APPROVED": reaching `APPROVED` or `PRODUCTION` with a `model_name` set
        requires a matching `ModelDefinitionRow` with `status == "APPROVED"`."""
        async with self.session_factory() as session:
            row = (
                await session.execute(select(AgentVersionRow).where(AgentVersionRow.id == version_id))
            ).scalar_one_or_none()
            if row is None:
                return None
            legal = _AGENT_VERSION_TRANSITIONS.get(row.status, set())
            if new_status not in legal:
                raise ValueError(f"Illegal agent version transition: {row.status} -> {new_status}")
            if new_status in ("APPROVED", "PRODUCTION") and row.model_name is not None:
                model = (
                    await session.execute(
                        select(ModelDefinitionRow).where(ModelDefinitionRow.model_name == row.model_name)
                    )
                ).scalar_one_or_none()
                if model is None or model.status != "APPROVED":
                    raise ValueError(
                        f"Model '{row.model_name}' is not an APPROVED model definition -- an agent "
                        "version may never be configured to use a model that isn't approved."
                    )
            if new_status == "PRODUCTION":
                prior_production = (
                    (
                        await session.execute(
                            select(AgentVersionRow).where(
                                AgentVersionRow.agent_type == row.agent_type,
                                AgentVersionRow.status == "PRODUCTION",
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for prior in prior_production:
                    prior.status = "RETIRED"
                row.deployment_timestamp = datetime.utcnow()
            if new_status == "APPROVED":
                row.approved_by = actor
                row.approved_at = datetime.utcnow()
            if evaluation_results is not None:
                row.evaluation_results = evaluation_results
            row.status = new_status
            await session.commit()
            await session.refresh(row)
        return _agent_version_to_dict(row)

    # -- model management (spec §43) -----------------------------------------------------

    async def seed_model_definitions(self, models: list[dict]) -> None:
        """Idempotent: seeds one `AVAILABLE`-then-`APPROVED` row per given
        `{provider, model_name}` pair that doesn't already exist, so the models this
        platform's agents are actually configured with always have a real, approved
        definition to point at (never fabricated after the fact)."""
        async with self.session_factory() as session:
            existing = set((await session.execute(select(ModelDefinitionRow.model_name))).scalars().all())
            for model in models:
                if model["model_name"] not in existing:
                    session.add(
                        ModelDefinitionRow(
                            provider=model["provider"],
                            model_name=model["model_name"],
                            status="APPROVED",
                            purpose=model.get("purpose"),
                            approved_at=datetime.utcnow(),
                        )
                    )
            await session.commit()

    async def create_model_definition(
        self,
        *,
        provider: str,
        model_name: str,
        version: str | None = None,
        purpose: str | None = None,
        context_window: int | None = None,
        cost_per_1k_input_tokens: float | None = None,
        cost_per_1k_output_tokens: float | None = None,
        notes: str | None = None,
    ) -> dict:
        row = ModelDefinitionRow(
            provider=provider,
            model_name=model_name,
            version=version,
            purpose=purpose,
            context_window=context_window,
            cost_per_1k_input_tokens=cost_per_1k_input_tokens,
            cost_per_1k_output_tokens=cost_per_1k_output_tokens,
            notes=notes,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return _model_definition_to_dict(row)

    async def list_model_definitions(self) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (await session.execute(select(ModelDefinitionRow).order_by(ModelDefinitionRow.created_at)))
                .scalars()
                .all()
            )
        return [_model_definition_to_dict(r) for r in rows]

    async def get_model_definition(self, model_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(ModelDefinitionRow).where(ModelDefinitionRow.id == model_id))
            ).scalar_one_or_none()
        return _model_definition_to_dict(row) if row is not None else None

    async def update_model_definition_status(
        self, model_id: str, new_status: str, *, actor: str | None = None
    ) -> dict | None:
        """Status is a plain admin-editable field (not a strict lifecycle like agent
        versions) since spec §43 lists `AVAILABLE`/`TESTING`/`APPROVED`/`DEPRECATED`/
        `DISABLED` as states an admin moves between directly as evaluation progresses."""
        async with self.session_factory() as session:
            row = (
                await session.execute(select(ModelDefinitionRow).where(ModelDefinitionRow.id == model_id))
            ).scalar_one_or_none()
            if row is None:
                return None
            row.status = new_status
            row.updated_by = actor
            row.updated_at = datetime.utcnow()
            if new_status == "APPROVED":
                row.approved_at = datetime.utcnow()
            await session.commit()
            await session.refresh(row)
        return _model_definition_to_dict(row)

    # -- audit log (spec §55) -------------------------------------------------------------

    async def record_audit_event(
        self,
        *,
        actor_user_id: str | None,
        action: str,
        resource_type: str,
        resource_id: str,
        before: dict | None = None,
        after: dict | None = None,
        reason: str | None = None,
    ) -> dict:
        """Append-only: there is no corresponding update/delete method, ever."""
        row = AuditEventRow(
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before=before,
            after=after,
            reason=reason,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return _audit_event_to_dict(row)

    async def list_audit_events(
        self, *, resource_type: str | None = None, limit: int = 100
    ) -> list[dict]:
        query = select(AuditEventRow).order_by(AuditEventRow.occurred_at.desc()).limit(limit)
        if resource_type is not None:
            query = query.where(AuditEventRow.resource_type == resource_type)
        async with self.session_factory() as session:
            rows = (await session.execute(query)).scalars().all()
        return [_audit_event_to_dict(r) for r in rows]

    async def list_roles(self) -> list[dict]:
        async with self.session_factory() as session:
            rows = (await session.execute(select(RoleRow).order_by(RoleRow.name))).scalars().all()
        return [_role_to_dict(r) for r in rows]

    async def get_role_by_name(self, name: str) -> dict | None:
        async with self.session_factory() as session:
            row = (await session.execute(select(RoleRow).where(RoleRow.name == name))).scalar_one_or_none()
        return _role_to_dict(row) if row is not None else None

    async def get_role_by_id(self, role_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (await session.execute(select(RoleRow).where(RoleRow.id == role_id))).scalar_one_or_none()
        return _role_to_dict(row) if row is not None else None

    async def create_organization(
        self,
        *,
        name: str,
        website: str | None = None,
        industry: str | None = None,
        company_type: str | None = None,
        country: str | None = None,
        state_region: str | None = None,
        billing_plan: str | None = None,
        account_owner: str | None = None,
        primary_contact: str | None = None,
        feature_package: str | None = None,
        notes: str | None = None,
    ) -> dict:
        row = OrganizationRow(
            name=name,
            website=website,
            industry=industry,
            company_type=company_type,
            country=country,
            state_region=state_region,
            billing_plan=billing_plan,
            account_owner=account_owner,
            primary_contact=primary_contact,
            feature_package=feature_package,
            notes=notes,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return _organization_to_dict(row)

    async def find_organization_by_name(self, name: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(OrganizationRow).where(OrganizationRow.name == name))
            ).scalar_one_or_none()
        return _organization_to_dict(row) if row is not None else None

    async def get_organization(self, organization_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(OrganizationRow).where(OrganizationRow.id == organization_id))
            ).scalar_one_or_none()
        return _organization_to_dict(row) if row is not None else None

    async def list_organizations(self) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (await session.execute(select(OrganizationRow).order_by(OrganizationRow.name))).scalars().all()
            )
        return [_organization_to_dict(r) for r in rows]

    async def create_user(
        self,
        *,
        first_name: str,
        last_name: str,
        email: str,
        organization_id: str,
        role_id: str,
        status: str,
        job_title: str | None = None,
        department: str | None = None,
        phone: str | None = None,
        country: str | None = None,
        state_region: str | None = None,
        primary_use_case: str | None = None,
        market_experience: str | None = None,
        expiration_at: datetime | None = None,
        created_by: str | None = None,
    ) -> dict:
        """Creates a `User` row. This is only ever called from the authenticated
        admin-create-user endpoint (`POST /admin/users`) — there is no other writer,
        by design (see docs/access-model.md "No Self-Registration")."""
        row = UserRow(
            first_name=first_name,
            last_name=last_name,
            email=email.lower(),
            organization_id=organization_id,
            job_title=job_title,
            department=department,
            phone=phone,
            country=country,
            state_region=state_region,
            primary_use_case=primary_use_case,
            market_experience=market_experience,
            role_id=role_id,
            status=status,
            expiration_at=_naive_utc(expiration_at),
            created_by=created_by,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return _user_to_dict(row)

    async def get_user_by_email(self, email: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(UserRow).where(UserRow.email == email.lower()))
            ).scalar_one_or_none()
        return _user_to_dict(row) if row is not None else None

    async def get_user_by_id(self, user_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (await session.execute(select(UserRow).where(UserRow.id == user_id))).scalar_one_or_none()
        return _user_to_dict(row) if row is not None else None

    async def list_users(self) -> list[dict]:
        async with self.session_factory() as session:
            rows = (await session.execute(select(UserRow).order_by(UserRow.created_at.desc()))).scalars().all()
        return [_user_to_dict(r) for r in rows]

    async def update_user_status(self, user_id: str, status: str) -> dict | None:
        async with self.session_factory() as session:
            row = (await session.execute(select(UserRow).where(UserRow.id == user_id))).scalar_one_or_none()
            if row is None:
                return None
            row.status = status
            row.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(row)
        return _user_to_dict(row)

    async def mark_user_activated(self, user_id: str) -> dict | None:
        """Promotes an `INVITED` user to `ACTIVE` and stamps `activated_at`/
        `last_login_at` — called only from a successful magic-link verification
        (`GET /auth/magic-link/verify`), never by any admin-facing endpoint (see
        docs/access-model.md §2: INVITED->ACTIVE only ever happens this way)."""
        now = datetime.utcnow()
        async with self.session_factory() as session:
            row = (await session.execute(select(UserRow).where(UserRow.id == user_id))).scalar_one_or_none()
            if row is None:
                return None
            row.status = "ACTIVE"
            row.activated_at = row.activated_at or now
            row.last_login_at = now
            row.updated_at = now
            await session.commit()
            await session.refresh(row)
        return _user_to_dict(row)

    async def record_user_login(self, user_id: str) -> None:
        async with self.session_factory() as session:
            row = (await session.execute(select(UserRow).where(UserRow.id == user_id))).scalar_one_or_none()
            if row is None:
                return
            row.last_login_at = datetime.utcnow()
            await session.commit()

    # -- magic link tokens ------------------------------------------------------------

    async def create_magic_link_token(
        self,
        *,
        user_id: str,
        token_hash: str,
        purpose: str,
        expires_at: datetime,
        requested_ip: str | None = None,
        user_agent: str | None = None,
    ) -> dict:
        row = MagicLinkTokenRow(
            user_id=user_id,
            token_hash=token_hash,
            purpose=purpose,
            expires_at=_naive_utc(expires_at),
            requested_ip=requested_ip,
            user_agent=user_agent,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return _magic_link_token_to_dict(row)

    async def get_magic_link_token_by_hash(self, token_hash: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(MagicLinkTokenRow).where(MagicLinkTokenRow.token_hash == token_hash))
            ).scalar_one_or_none()
        return _magic_link_token_to_dict(row) if row is not None else None

    async def consume_magic_link_token(self, token_id: str) -> dict | None:
        """Marks a token consumed. Applying this exactly once (verified by the caller
        checking `consumed_at is None` before calling) is what makes the token
        single-use — spec §19's "Immediate invalidation after use"."""
        async with self.session_factory() as session:
            row = (
                await session.execute(select(MagicLinkTokenRow).where(MagicLinkTokenRow.id == token_id))
            ).scalar_one_or_none()
            if row is None:
                return None
            row.consumed_at = datetime.utcnow()
            await session.commit()
            await session.refresh(row)
        return _magic_link_token_to_dict(row)

    async def revoke_unconsumed_magic_link_tokens_for_user(self, user_id: str, *, purpose: str | None = None) -> int:
        """Invalidates every outstanding (unconsumed, unrevoked) token for a user —
        used both by "Resend Invitation" (spec §18: "Invalidate all prior unused
        invitation links") and defensively whenever a fresh token is issued for the
        same purpose, so an old email link can never be used alongside a new one."""
        async with self.session_factory() as session:
            stmt = select(MagicLinkTokenRow).where(
                MagicLinkTokenRow.user_id == user_id,
                MagicLinkTokenRow.consumed_at.is_(None),
                MagicLinkTokenRow.revoked_at.is_(None),
            )
            if purpose is not None:
                stmt = stmt.where(MagicLinkTokenRow.purpose == purpose)
            rows = (await session.execute(stmt)).scalars().all()
            now = datetime.utcnow()
            for row in rows:
                row.revoked_at = now
            await session.commit()
        return len(rows)

    # -- sessions -----------------------------------------------------------------

    async def create_session(
        self, *, user_id: str, expires_at: datetime, ip_address: str | None = None, user_agent: str | None = None
    ) -> dict:
        row = SessionRow(user_id=user_id, expires_at=_naive_utc(expires_at), ip_address=ip_address, user_agent=user_agent)
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return _session_to_dict(row)

    async def get_session(self, session_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (await session.execute(select(SessionRow).where(SessionRow.id == session_id))).scalar_one_or_none()
        return _session_to_dict(row) if row is not None else None

    async def list_sessions_for_user(self, user_id: str) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(SessionRow).where(SessionRow.user_id == user_id).order_by(SessionRow.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
        return [_session_to_dict(r) for r in rows]

    async def revoke_session(self, session_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (await session.execute(select(SessionRow).where(SessionRow.id == session_id))).scalar_one_or_none()
            if row is None:
                return None
            row.revoked_at = datetime.utcnow()
            await session.commit()
            await session.refresh(row)
        return _session_to_dict(row)

    async def touch_session(self, session_id: str) -> None:
        async with self.session_factory() as session:
            row = (await session.execute(select(SessionRow).where(SessionRow.id == session_id))).scalar_one_or_none()
            if row is None:
                return
            row.last_seen_at = datetime.utcnow()
            await session.commit()

    # -- chat conversations (spec §29) -------------------------------------------------

    async def create_chat_conversation(self, *, conversation_id: str, user_id: str, organization_id: str | None) -> dict:
        row = ChatConversationRow(id=conversation_id, user_id=user_id, organization_id=organization_id)
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
        return {"id": row.id, "user_id": row.user_id, "organization_id": row.organization_id, "created_at": row.created_at}

    async def save_chat_message(
        self,
        *,
        conversation_id: str,
        role: str,
        content: str,
        citations: list | None = None,
        freshness: dict | None = None,
        tool_used: str | None = None,
        model: str | None = None,
        latency_ms: float | None = None,
        permissions_context: dict | None = None,
    ) -> dict:
        """Persists one chat turn. Deliberately has no field for a private
        chain-of-thought — only what a `ChatMessage` API response already exposes,
        plus metadata about how it was produced (spec §29)."""
        row = ChatMessageRow(
            conversation_id=conversation_id,
            role=role,
            content=content,
            citations=citations or [],
            freshness=freshness or {},
            tool_used=tool_used,
            model=model,
            latency_ms=latency_ms,
            permissions_context=permissions_context or {},
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return {
            "id": row.id,
            "conversation_id": row.conversation_id,
            "role": row.role,
            "content": row.content,
            "citations": row.citations,
            "freshness": row.freshness,
            "tool_used": row.tool_used,
            "model": row.model,
            "latency_ms": row.latency_ms,
            "permissions_context": row.permissions_context,
            "created_at": row.created_at,
        }

    async def get_chat_conversation(self, conversation_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(ChatConversationRow).where(ChatConversationRow.id == conversation_id))
            ).scalar_one_or_none()
        if row is None:
            return None
        return {"id": row.id, "user_id": row.user_id, "organization_id": row.organization_id, "created_at": row.created_at}

    async def list_chat_messages(self, conversation_id: str) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(ChatMessageRow)
                        .where(ChatMessageRow.conversation_id == conversation_id)
                        .order_by(ChatMessageRow.created_at)
                    )
                )
                .scalars()
                .all()
            )
        return [
            {
                "id": r.id,
                "conversation_id": r.conversation_id,
                "role": r.role,
                "content": r.content,
                "citations": r.citations,
                "freshness": r.freshness,
                "tool_used": r.tool_used,
                "model": r.model,
                "latency_ms": r.latency_ms,
                "permissions_context": r.permissions_context,
                "created_at": r.created_at,
            }
            for r in rows
        ]

    async def list_chat_conversations(self, *, user_id: str | None = None) -> list[dict]:
        """Admin-visibility listing (spec §29: "Support administrator access to chat
        usage metadata according to role and policy") — filterable by user."""
        async with self.session_factory() as session:
            stmt = select(ChatConversationRow).order_by(ChatConversationRow.created_at.desc())
            if user_id is not None:
                stmt = stmt.where(ChatConversationRow.user_id == user_id)
            rows = (await session.execute(stmt)).scalars().all()
        return [
            {"id": r.id, "user_id": r.user_id, "organization_id": r.organization_id, "created_at": r.created_at}
            for r in rows
        ]

    # -- writes ---------------------------------------------------------------------

    async def save_trade_idea(self, trade: TradeIdea, forecast: PriceForecast | None) -> None:
        row = TradeIdeaRow(
            trade_id=str(trade.trade_id),
            organization_id=trade.organization_id,
            strategy=trade.strategy,
            instrument=trade.instrument,
            instrument_type=trade.instrument_type.value,
            direction=trade.direction.value,
            entry=trade.entry,
            target=trade.target,
            stop_or_invalidation=trade.stop_or_invalidation,
            time_horizon=trade.time_horizon,
            expected_return=trade.expected_return,
            expected_loss=trade.expected_loss,
            probability_success=trade.probability_success,
            confidence=trade.confidence,
            thesis=trade.thesis,
            catalysts=trade.catalysts,
            risks=trade.risks,
            invalidation_conditions=trade.invalidation_conditions,
            supporting_data=trade.supporting_data,
            source_citations=trade.source_citations,
            created_at=_naive_utc(trade.created_at),
            expires_at=_naive_utc(trade.expires_at),
            forecast=forecast.model_dump(mode="json") if forecast is not None else None,
        )
        async with self.session_factory() as session:
            await session.merge(row)
            await session.commit()

    async def save_signal(self, signal: Signal) -> None:
        row = SignalRow(
            id=str(signal.id),
            organization_id=signal.organization_id,
            workspace_id=signal.workspace_id,
            signal_type=signal.signal_type.value,
            category=signal.category,
            subcategory=signal.subcategory,
            source_ids=signal.source_ids,
            detected_at=_naive_utc(signal.detected_at),
            effective_at=_naive_utc(signal.effective_at),
            market=signal.market,
            geography=signal.geography,
            asset_ids=signal.asset_ids,
            headline=signal.headline,
            description=signal.description,
            previous_value=signal.previous_value,
            current_value=signal.current_value,
            absolute_change=signal.absolute_change,
            percent_change=signal.percent_change,
            z_score=signal.z_score,
            historical_percentile=signal.historical_percentile,
            materiality_score=signal.materiality_score,
            novelty_score=signal.novelty_score,
            confidence=signal.confidence,
            direction=signal.direction.value,
            time_horizon=signal.time_horizon,
            data_quality=signal.data_quality.value,
            citations=[c.model_dump(mode="json") for c in signal.citations],
            affected_agents=signal.affected_agents,
            affected_business_functions=signal.affected_business_functions,
            status=signal.status.value,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    async def list_signals(
        self,
        *,
        organization_id: str | None = None,
        platform_only: bool = False,
        market: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        min_materiality: float | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Ranked by materiality (highest first), then recency. `organization_id`, when
        given, includes both that organization's own signals AND every platform-wide
        signal (`organization_id IS NULL`) -- the only kind Milestone 1's detector
        produces -- rather than hiding the global feed from every tenant. `until`
        (docs/alpha-intelligence.md section 9, AlphaReplay(TM)) filters to signals
        detected at-or-before that moment, for "what did we know as of <timestamp>"
        queries. `platform_only` (docs/alpha-intelligence.md section 11.1, Milestone
        9) restricts to `organization_id IS NULL` rows only -- for a caller whose own
        organization couldn't be resolved and who isn't a cross-organization admin,
        so they see the platform-wide feed rather than every organization's data."""
        query = select(SignalRow).order_by(SignalRow.materiality_score.desc(), SignalRow.detected_at.desc()).limit(limit)
        if organization_id is not None:
            query = query.where(
                (SignalRow.organization_id == organization_id) | (SignalRow.organization_id.is_(None))
            )
        elif platform_only:
            query = query.where(SignalRow.organization_id.is_(None))
        if market is not None:
            query = query.where(SignalRow.market == market)
        if until is not None:
            query = query.where(SignalRow.detected_at <= _naive_utc(until))
        if since is not None:
            query = query.where(SignalRow.detected_at >= _naive_utc(since))
        if min_materiality is not None:
            query = query.where(SignalRow.materiality_score >= min_materiality)
        async with self.session_factory() as session:
            rows = (await session.execute(query)).scalars().all()
        return [_signal_row_to_dict(r) for r in rows]

    async def get_signal(self, signal_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (await session.execute(select(SignalRow).where(SignalRow.id == signal_id))).scalar_one_or_none()
        return _signal_row_to_dict(row) if row is not None else None

    async def get_signal_baselines(self) -> dict[str, dict]:
        """Every `SignalBaselineRow`, keyed by its detector key -- a small, bounded
        table (one row per tracked metric), so no filtering is needed to keep this
        cheap."""
        async with self.session_factory() as session:
            rows = (await session.execute(select(SignalBaselineRow))).scalars().all()
        return {
            r.key: {
                "value": r.value,
                "rolling_window": r.rolling_window,
                "signal_emitted_history": r.signal_emitted_history,
                "observed_at": r.observed_at,
            }
            for r in rows
        }

    async def save_signal_baselines(self, baselines: dict[str, dict]) -> None:
        async with self.session_factory() as session:
            for key, snapshot in baselines.items():
                row = SignalBaselineRow(
                    key=key,
                    value=snapshot["value"],
                    rolling_window=snapshot["rolling_window"],
                    signal_emitted_history=snapshot.get("signal_emitted_history", []),
                    observed_at=_naive_utc(snapshot["observed_at"]),
                )
                await session.merge(row)
            await session.commit()

    async def save_impact_analysis(self, analysis: ImpactAnalysis) -> None:
        row = ImpactAnalysisRow(
            id=str(analysis.id),
            signal_id=str(analysis.signal_id),
            organization_id=analysis.organization_id,
            event_type=analysis.event_type.value,
            physical_impact=analysis.physical_impact,
            supply_impact_bcf_day=analysis.supply_impact_bcf_day,
            demand_impact_bcf_day=analysis.demand_impact_bcf_day,
            storage_impact_bcf=analysis.storage_impact_bcf,
            expected_duration=analysis.expected_duration,
            affected_geographies=analysis.affected_geographies,
            affected_assets=analysis.affected_assets,
            affected_markets=analysis.affected_markets,
            affected_contracts=analysis.affected_contracts,
            basis_implications=analysis.basis_implications,
            curve_implications=analysis.curve_implications,
            volatility_implications=analysis.volatility_implications,
            portfolio_implications=analysis.portfolio_implications,
            risk_implications=analysis.risk_implications,
            bullish_bearish=analysis.bullish_bearish.value,
            magnitude=analysis.magnitude,
            confidence=analysis.confidence,
            assumptions=analysis.assumptions,
            uncertainties=analysis.uncertainties,
            alternative_interpretations=analysis.alternative_interpretations,
            data_sources=analysis.data_sources,
            agent_contributors=analysis.agent_contributors,
            chain=[edge.model_dump(mode="json") for edge in analysis.chain],
            created_at=_naive_utc(analysis.created_at),
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    async def list_impact_analyses(
        self,
        *,
        signal_id: str | None = None,
        organization_id: str | None = None,
        platform_only: bool = False,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
    ) -> list[dict]:
        query = select(ImpactAnalysisRow).order_by(ImpactAnalysisRow.created_at.desc()).limit(limit)
        if signal_id is not None:
            query = query.where(ImpactAnalysisRow.signal_id == signal_id)
        if organization_id is not None:
            query = query.where(
                (ImpactAnalysisRow.organization_id == organization_id)
                | (ImpactAnalysisRow.organization_id.is_(None))
            )
        elif platform_only:
            query = query.where(ImpactAnalysisRow.organization_id.is_(None))
        if until is not None:
            query = query.where(ImpactAnalysisRow.created_at <= _naive_utc(until))
        if since is not None:
            query = query.where(ImpactAnalysisRow.created_at >= _naive_utc(since))
        async with self.session_factory() as session:
            rows = (await session.execute(query)).scalars().all()
        return [_impact_analysis_row_to_dict(r) for r in rows]

    async def get_impact_analysis(self, impact_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(ImpactAnalysisRow).where(ImpactAnalysisRow.id == impact_id))
            ).scalar_one_or_none()
        return _impact_analysis_row_to_dict(row) if row is not None else None

    async def get_latest_impact_analysis_for_signal(self, signal_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(ImpactAnalysisRow)
                    .where(ImpactAnalysisRow.signal_id == signal_id)
                    .order_by(ImpactAnalysisRow.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        return _impact_analysis_row_to_dict(row) if row is not None else None

    async def save_agent_forecast(self, forecast: AgentForecast) -> None:
        row = AgentForecastRow(
            id=str(forecast.id),
            agent_id=forecast.agent_id,
            agent_type=forecast.agent_type.value,
            agent_version=forecast.agent_version,
            organization_id=forecast.organization_id,
            forecast_type=forecast.forecast_type,
            target=forecast.target,
            market=forecast.market,
            horizon=forecast.horizon,
            forecast_value=forecast.forecast_value,
            direction=forecast.direction.value,
            probability=forecast.probability,
            confidence=forecast.confidence,
            drivers=forecast.drivers,
            citations=[c.model_dump(mode="json") for c in forecast.citations],
            created_at=_naive_utc(forecast.created_at),
            expires_at=_naive_utc(forecast.expires_at),
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    async def list_agent_forecasts(
        self, *, market: str | None = None, since: datetime | None = None, limit: int = 100
    ) -> list[dict]:
        query = select(AgentForecastRow).order_by(AgentForecastRow.created_at.desc()).limit(limit)
        if market is not None:
            query = query.where(AgentForecastRow.market == market)
        if since is not None:
            query = query.where(AgentForecastRow.created_at >= _naive_utc(since))
        async with self.session_factory() as session:
            rows = (await session.execute(query)).scalars().all()
        return [_agent_forecast_row_to_dict(r) for r in rows]

    async def save_agent_alpha_score(self, score: AgentAlphaScore) -> None:
        row = AgentAlphaScoreRow(
            agent_type=score.agent_type.value,
            score=score.score,
            method=score.method,
            sample_size=score.sample_size,
            components=score.components,
            computed_at=_naive_utc(score.computed_at),
        )
        async with self.session_factory() as session:
            await session.merge(row)
            await session.commit()

    async def list_agent_alpha_scores(self) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (await session.execute(select(AgentAlphaScoreRow).order_by(AgentAlphaScoreRow.agent_type)))
                .scalars()
                .all()
            )
        return [_agent_alpha_score_row_to_dict(r) for r in rows]

    async def get_agent_alpha_score(self, agent_type: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(AgentAlphaScoreRow).where(AgentAlphaScoreRow.agent_type == agent_type))
            ).scalar_one_or_none()
        return _agent_alpha_score_row_to_dict(row) if row is not None else None

    async def save_consensus_view(self, view: ConsensusView) -> None:
        row = ConsensusViewRow(
            id=str(view.id),
            organization_id=view.organization_id,
            consensus_type=view.consensus_type,
            market=view.market,
            target=view.target,
            horizon=view.horizon,
            consensus_value=view.consensus_value,
            bull_probability=view.bull_probability,
            bear_probability=view.bear_probability,
            neutral_probability=view.neutral_probability,
            confidence=view.confidence,
            dispersion=view.dispersion,
            agreement_label=view.agreement_label,
            agent_count=view.agent_count,
            agent_weights=[w.model_dump(mode="json") for w in view.agent_weights],
            leading_agents=view.leading_agents,
            dissenting_agents=view.dissenting_agents,
            drivers=view.drivers,
            risks=view.risks,
            market_consensus_value=view.market_consensus_value,
            variance_vs_market=view.variance_vs_market,
            created_at=_naive_utc(view.created_at),
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    async def list_consensus_views(
        self,
        *,
        consensus_type: str | None = None,
        market: str | None = None,
        organization_id: str | None = None,
        platform_only: bool = False,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
    ) -> list[dict]:
        query = select(ConsensusViewRow).order_by(ConsensusViewRow.created_at.desc()).limit(limit)
        if consensus_type is not None:
            query = query.where(ConsensusViewRow.consensus_type == consensus_type)
        if market is not None:
            query = query.where(ConsensusViewRow.market == market)
        if organization_id is not None:
            query = query.where(
                (ConsensusViewRow.organization_id == organization_id) | (ConsensusViewRow.organization_id.is_(None))
            )
        elif platform_only:
            query = query.where(ConsensusViewRow.organization_id.is_(None))
        if until is not None:
            query = query.where(ConsensusViewRow.created_at <= _naive_utc(until))
        if since is not None:
            query = query.where(ConsensusViewRow.created_at >= _naive_utc(since))
        async with self.session_factory() as session:
            rows = (await session.execute(query)).scalars().all()
        return [_consensus_view_row_to_dict(r) for r in rows]

    async def get_consensus_view(self, consensus_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(ConsensusViewRow).where(ConsensusViewRow.id == consensus_id))
            ).scalar_one_or_none()
        return _consensus_view_row_to_dict(row) if row is not None else None

    async def get_latest_consensus_view_for_market(self, market: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(ConsensusViewRow)
                    .where(ConsensusViewRow.market == market)
                    .order_by(ConsensusViewRow.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        return _consensus_view_row_to_dict(row) if row is not None else None

    async def save_scenario_run(self, run: ScenarioRunResult) -> None:
        row = ScenarioRunRow(
            id=str(run.id),
            organization_id=run.organization_id,
            scenario_name=run.scenario_name,
            scenario_description=run.scenario_description,
            base_scenario_ids=run.base_scenario_ids,
            price_shock_pct=run.price_shock_pct,
            demand_shock_bcf_d=run.demand_shock_bcf_d,
            supply_shock_bcf_d=run.supply_shock_bcf_d,
            volatility_multiplier=run.volatility_multiplier,
            portfolio_pnl=run.portfolio_pnl,
            strategy_pnl=run.strategy_pnl,
            margin_impact=run.margin_impact,
            var_impact=run.var_impact,
            largest_risk_contributor=run.largest_risk_contributor,
            requested_by=run.requested_by,
            run_at=_naive_utc(run.run_at),
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    async def list_scenario_runs(
        self,
        *,
        organization_id: str | None = None,
        platform_only: bool = False,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
    ) -> list[dict]:
        query = select(ScenarioRunRow).order_by(ScenarioRunRow.run_at.desc()).limit(limit)
        if organization_id is not None:
            query = query.where(
                (ScenarioRunRow.organization_id == organization_id) | (ScenarioRunRow.organization_id.is_(None))
            )
        elif platform_only:
            query = query.where(ScenarioRunRow.organization_id.is_(None))
        if until is not None:
            query = query.where(ScenarioRunRow.run_at <= _naive_utc(until))
        if since is not None:
            query = query.where(ScenarioRunRow.run_at >= _naive_utc(since))
        async with self.session_factory() as session:
            rows = (await session.execute(query)).scalars().all()
        return [_scenario_run_row_to_dict(r) for r in rows]

    async def get_scenario_run(self, run_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(ScenarioRunRow).where(ScenarioRunRow.id == run_id))
            ).scalar_one_or_none()
        return _scenario_run_row_to_dict(row) if row is not None else None

    async def save_memory_record(self, memory: MemoryRecord) -> None:
        row = MemoryRecordRow(
            id=str(memory.id),
            organization_id=memory.organization_id,
            memory_type=memory.memory_type.value,
            trade_id=str(memory.trade_id) if memory.trade_id is not None else None,
            market=memory.market,
            strategy=memory.strategy,
            title=memory.title,
            summary=memory.summary,
            outcome_quadrant=memory.outcome_quadrant.value if memory.outcome_quadrant is not None else None,
            structured_context=memory.structured_context,
            tags=memory.tags,
            created_at=_naive_utc(memory.created_at),
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    async def list_memory_records(
        self,
        *,
        memory_type: str | None = None,
        market: str | None = None,
        organization_id: str | None = None,
        platform_only: bool = False,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
    ) -> list[dict]:
        query = select(MemoryRecordRow).order_by(MemoryRecordRow.created_at.desc()).limit(limit)
        if memory_type is not None:
            query = query.where(MemoryRecordRow.memory_type == memory_type)
        if market is not None:
            query = query.where(MemoryRecordRow.market == market)
        if organization_id is not None:
            query = query.where(
                (MemoryRecordRow.organization_id == organization_id) | (MemoryRecordRow.organization_id.is_(None))
            )
        elif platform_only:
            query = query.where(MemoryRecordRow.organization_id.is_(None))
        if until is not None:
            query = query.where(MemoryRecordRow.created_at <= _naive_utc(until))
        if since is not None:
            query = query.where(MemoryRecordRow.created_at >= _naive_utc(since))
        async with self.session_factory() as session:
            rows = (await session.execute(query)).scalars().all()
        return [_memory_record_row_to_dict(r) for r in rows]

    async def get_memory_record(self, memory_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(MemoryRecordRow).where(MemoryRecordRow.id == memory_id))
            ).scalar_one_or_none()
        return _memory_record_row_to_dict(row) if row is not None else None

    async def save_lesson_proposal(self, lesson: LessonProposal) -> None:
        row = LessonProposalRow(
            id=str(lesson.id),
            organization_id=lesson.organization_id,
            memory_record_id=str(lesson.memory_record_id),
            proposed_lesson=lesson.proposed_lesson,
            rationale=lesson.rationale,
            status=lesson.status.value,
            reviewed_by=lesson.reviewed_by,
            reviewed_at=_naive_utc(lesson.reviewed_at) if lesson.reviewed_at is not None else None,
            created_at=_naive_utc(lesson.created_at),
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    async def list_lesson_proposals(
        self,
        *,
        status: str | None = None,
        organization_id: str | None = None,
        platform_only: bool = False,
        limit: int = 50,
    ) -> list[dict]:
        query = select(LessonProposalRow).order_by(LessonProposalRow.created_at.desc()).limit(limit)
        if status is not None:
            query = query.where(LessonProposalRow.status == status)
        if organization_id is not None:
            query = query.where(
                (LessonProposalRow.organization_id == organization_id) | (LessonProposalRow.organization_id.is_(None))
            )
        elif platform_only:
            query = query.where(LessonProposalRow.organization_id.is_(None))
        async with self.session_factory() as session:
            rows = (await session.execute(query)).scalars().all()
        return [_lesson_proposal_row_to_dict(r) for r in rows]

    async def get_lesson_proposal(self, lesson_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(LessonProposalRow).where(LessonProposalRow.id == lesson_id))
            ).scalar_one_or_none()
        return _lesson_proposal_row_to_dict(row) if row is not None else None

    async def update_lesson_proposal_status(
        self, lesson_id: str, *, status: str, reviewed_by: str, reviewed_at: datetime
    ) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(LessonProposalRow).where(LessonProposalRow.id == lesson_id))
            ).scalar_one_or_none()
            if row is None:
                return None
            row.status = status
            row.reviewed_by = reviewed_by
            row.reviewed_at = _naive_utc(reviewed_at)
            await session.commit()
            return _lesson_proposal_row_to_dict(row)

    async def save_market_observation(self, obs: TimeSeriesObservation) -> None:
        """Persists `obs` as the new current revision of its `series_id`+
        `observation_time` (docs/alpha-intelligence.md section 9) -- closes out the
        prior current revision's `valid_to` (bitemporal supersession) rather than
        overwriting it, so history is append-only and an "as known at <timestamp>"
        query still recovers exactly what was believed at any past moment. A
        duplicate or stale write (a revision number no higher than the current one)
        is a no-op rather than corrupting the revision history."""
        publication_time = _naive_utc(obs.publication_time)
        async with self.session_factory() as session:
            prior = (
                await session.execute(
                    select(MarketObservationRow)
                    .where(
                        MarketObservationRow.series_id == obs.series_id,
                        MarketObservationRow.observation_time == _naive_utc(obs.observation_time),
                        MarketObservationRow.valid_to.is_(None),
                    )
                    .order_by(MarketObservationRow.revision_number.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if prior is not None:
                if prior.revision_number >= obs.revision_number:
                    return
                prior.valid_to = publication_time
            row = MarketObservationRow(
                id=str(obs.id),
                source=obs.source,
                source_type=obs.source_type.value,
                series_id=obs.series_id,
                symbol=obs.symbol,
                commodity=obs.commodity,
                category=obs.category,
                sub_category=obs.sub_category,
                geography=obs.geography,
                location=obs.location,
                value=obs.value,
                unit=obs.unit,
                observation_time=_naive_utc(obs.observation_time),
                publication_time=publication_time,
                revision_number=obs.revision_number,
                quality_score=obs.quality_score,
                confidence=obs.confidence,
                metadata_=obs.metadata,
                lineage=obs.lineage.model_dump(mode="json"),
                revision_time=_naive_utc(obs.revision_time) if obs.revision_time is not None else None,
                valid_from=publication_time,
                valid_to=None,
                received_time=_naive_utc(obs.received_time),
                created_at=_naive_utc(obs.created_at),
            )
            session.add(row)
            await session.commit()

    async def list_market_observations_as_of(
        self,
        *,
        series_id: str | None = None,
        as_of: datetime | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """The bitemporal "as known at <as_of>" query: returns whichever revision of
        each observation was current at that moment (`publication_time <= as_of`
        AND (`valid_to IS NULL` OR `valid_to > as_of`)) -- honoring later corrections
        exactly as they stood then, not as they stand today. Omitting `as_of`
        returns each series' latest current revision."""
        query = select(MarketObservationRow).order_by(MarketObservationRow.observation_time.desc()).limit(limit)
        if series_id is not None:
            query = query.where(MarketObservationRow.series_id == series_id)
        if as_of is not None:
            as_of_naive = _naive_utc(as_of)
            query = query.where(
                MarketObservationRow.publication_time <= as_of_naive,
                (MarketObservationRow.valid_to.is_(None)) | (MarketObservationRow.valid_to > as_of_naive),
            )
        else:
            query = query.where(MarketObservationRow.valid_to.is_(None))
        async with self.session_factory() as session:
            rows = (await session.execute(query)).scalars().all()
        return [_market_observation_row_to_dict(r) for r in rows]

    async def save_intelligence_brief(self, brief: IntelligenceBrief) -> None:
        row = IntelligenceBriefRow(
            id=str(brief.id),
            organization_id=brief.organization_id,
            market=brief.market,
            period_start=_naive_utc(brief.period_start),
            period_end=_naive_utc(brief.period_end),
            headline=brief.headline,
            summary=brief.summary,
            top_signals=[s.model_dump(mode="json") for s in brief.top_signals],
            top_impacts=[i.model_dump(mode="json") for i in brief.top_impacts],
            consensus_highlights=[v.model_dump(mode="json") for v in brief.consensus_highlights],
            notable_scenario_runs=[r.model_dump(mode="json") for r in brief.notable_scenario_runs],
            pending_lessons=[lp.model_dump(mode="json") for lp in brief.pending_lessons],
            generated_at=_naive_utc(brief.generated_at),
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    async def list_intelligence_briefs(
        self,
        *,
        market: str | None = None,
        organization_id: str | None = None,
        platform_only: bool = False,
        limit: int = 20,
    ) -> list[dict]:
        """... platform_only (docs/alpha-intelligence.md section 11.1, Milestone
        9) restricts to `organization_id IS NULL` rows only -- for a caller whose own
        organization couldn't be resolved and who isn't a cross-organization admin,
        so they see the platform-wide feed rather than every organization's data."""
        query = select(IntelligenceBriefRow).order_by(IntelligenceBriefRow.generated_at.desc()).limit(limit)
        if market is not None:
            query = query.where(IntelligenceBriefRow.market == market)
        if organization_id is not None:
            query = query.where(
                (IntelligenceBriefRow.organization_id == organization_id)
                | (IntelligenceBriefRow.organization_id.is_(None))
            )
        elif platform_only:
            query = query.where(IntelligenceBriefRow.organization_id.is_(None))
        async with self.session_factory() as session:
            rows = (await session.execute(query)).scalars().all()
        return [_intelligence_brief_row_to_dict(r) for r in rows]

    async def get_intelligence_brief(self, brief_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(IntelligenceBriefRow).where(IntelligenceBriefRow.id == brief_id))
            ).scalar_one_or_none()
        return _intelligence_brief_row_to_dict(row) if row is not None else None

    # -- Enterprise Data Platform (docs/alpha-intelligence.md section 11, Milestone 8) --

    async def save_workspace(self, workspace: Workspace) -> None:
        row = WorkspaceRow(
            id=str(workspace.id),
            organization_id=workspace.organization_id,
            name=workspace.name,
            description=workspace.description,
            created_by=workspace.created_by,
            created_at=_naive_utc(workspace.created_at),
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    async def list_workspaces(self, *, organization_id: str | None = None) -> list[dict]:
        query = select(WorkspaceRow).order_by(WorkspaceRow.created_at.desc())
        if organization_id is not None:
            query = query.where(WorkspaceRow.organization_id == organization_id)
        async with self.session_factory() as session:
            rows = (await session.execute(query)).scalars().all()
        return [_workspace_row_to_dict(r) for r in rows]

    async def get_workspace(self, workspace_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (await session.execute(select(WorkspaceRow).where(WorkspaceRow.id == workspace_id))).scalar_one_or_none()
        return _workspace_row_to_dict(row) if row is not None else None

    async def update_workspace(self, workspace_id: str, **fields) -> dict | None:
        async with self.session_factory() as session:
            row = (await session.execute(select(WorkspaceRow).where(WorkspaceRow.id == workspace_id))).scalar_one_or_none()
            if row is None:
                return None
            for key, value in fields.items():
                setattr(row, key, value)
            await session.commit()
            return _workspace_row_to_dict(row)

    async def delete_workspace(self, workspace_id: str) -> bool:
        async with self.session_factory() as session:
            row = (await session.execute(select(WorkspaceRow).where(WorkspaceRow.id == workspace_id))).scalar_one_or_none()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def add_workspace_member(self, workspace_id: str, user_id: str, *, added_by: str | None = None) -> None:
        async with self.session_factory() as session:
            existing = (
                await session.execute(
                    select(WorkspaceMemberRow).where(
                        WorkspaceMemberRow.workspace_id == workspace_id, WorkspaceMemberRow.user_id == user_id
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return
            session.add(WorkspaceMemberRow(workspace_id=workspace_id, user_id=user_id, added_by=added_by))
            await session.commit()

    async def remove_workspace_member(self, workspace_id: str, user_id: str) -> bool:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(WorkspaceMemberRow).where(
                        WorkspaceMemberRow.workspace_id == workspace_id, WorkspaceMemberRow.user_id == user_id
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def list_workspace_members(self, workspace_id: str) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(select(WorkspaceMemberRow).where(WorkspaceMemberRow.workspace_id == workspace_id))
            ).scalars().all()
        return [
            {"workspace_id": r.workspace_id, "user_id": r.user_id, "added_by": r.added_by, "added_at": r.added_at}
            for r in rows
        ]

    async def save_enterprise_data_source(self, source: EnterpriseDataSource) -> None:
        row = EnterpriseDataSourceRow(
            id=str(source.id),
            organization_id=source.organization_id,
            workspace_id=str(source.workspace_id) if source.workspace_id is not None else None,
            name=source.name,
            connector_type=source.connector_type.value,
            classification=source.classification.value,
            status=source.status.value,
            description=source.description,
            connection_config=source.connection_config,
            created_by=source.created_by,
            created_at=_naive_utc(source.created_at),
            updated_at=_naive_utc(source.updated_at),
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    async def list_enterprise_data_sources(
        self, *, organization_id: str | None = None, workspace_id: str | None = None
    ) -> list[dict]:
        query = select(EnterpriseDataSourceRow).order_by(EnterpriseDataSourceRow.created_at.desc())
        if organization_id is not None:
            query = query.where(EnterpriseDataSourceRow.organization_id == organization_id)
        if workspace_id is not None:
            query = query.where(EnterpriseDataSourceRow.workspace_id == workspace_id)
        async with self.session_factory() as session:
            rows = (await session.execute(query)).scalars().all()
        return [_enterprise_data_source_row_to_dict(r) for r in rows]

    async def get_enterprise_data_source(self, source_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(EnterpriseDataSourceRow).where(EnterpriseDataSourceRow.id == source_id))
            ).scalar_one_or_none()
        return _enterprise_data_source_row_to_dict(row) if row is not None else None

    async def update_enterprise_data_source(self, source_id: str, **fields) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(EnterpriseDataSourceRow).where(EnterpriseDataSourceRow.id == source_id))
            ).scalar_one_or_none()
            if row is None:
                return None
            for key, value in fields.items():
                setattr(row, key, value)
            row.updated_at = datetime.utcnow()
            await session.commit()
            return _enterprise_data_source_row_to_dict(row)

    async def delete_enterprise_data_source(self, source_id: str) -> bool:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(EnterpriseDataSourceRow).where(EnterpriseDataSourceRow.id == source_id))
            ).scalar_one_or_none()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def save_enterprise_dataset(self, dataset: EnterpriseDataset) -> None:
        row = EnterpriseDatasetRow(
            id=str(dataset.id),
            source_id=str(dataset.source_id),
            organization_id=dataset.organization_id,
            name=dataset.name,
            domain=dataset.domain.value,
            classification=dataset.classification.value,
            schema_summary=dataset.schema_summary,
            row_count=dataset.row_count,
            last_synced_at=_naive_utc(dataset.last_synced_at) if dataset.last_synced_at is not None else None,
            created_at=_naive_utc(dataset.created_at),
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    async def list_enterprise_datasets(
        self, *, source_id: str | None = None, organization_id: str | None = None
    ) -> list[dict]:
        query = select(EnterpriseDatasetRow).order_by(EnterpriseDatasetRow.created_at.desc())
        if source_id is not None:
            query = query.where(EnterpriseDatasetRow.source_id == source_id)
        if organization_id is not None:
            query = query.where(EnterpriseDatasetRow.organization_id == organization_id)
        async with self.session_factory() as session:
            rows = (await session.execute(query)).scalars().all()
        return [_enterprise_dataset_row_to_dict(r) for r in rows]

    async def get_enterprise_dataset(self, dataset_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(EnterpriseDatasetRow).where(EnterpriseDatasetRow.id == dataset_id))
            ).scalar_one_or_none()
        return _enterprise_dataset_row_to_dict(row) if row is not None else None

    async def update_enterprise_dataset_sync(
        self, dataset_id: str, *, schema_summary: dict | None = None, row_count: int
    ) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(EnterpriseDatasetRow).where(EnterpriseDatasetRow.id == dataset_id))
            ).scalar_one_or_none()
            if row is None:
                return None
            if schema_summary is not None:
                row.schema_summary = schema_summary
            row.row_count = row_count
            row.last_synced_at = datetime.utcnow()
            await session.commit()
            return _enterprise_dataset_row_to_dict(row)

    async def save_enterprise_data_entitlement(self, entitlement: EnterpriseDataEntitlement) -> None:
        row = EnterpriseDataEntitlementRow(
            id=str(entitlement.id),
            dataset_id=str(entitlement.dataset_id),
            principal_type=entitlement.principal_type.value,
            principal_id=entitlement.principal_id,
            granted_by=entitlement.granted_by,
            granted_at=_naive_utc(entitlement.granted_at),
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    async def list_enterprise_data_entitlements(self, dataset_id: str) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(EnterpriseDataEntitlementRow).where(EnterpriseDataEntitlementRow.dataset_id == dataset_id)
                )
            ).scalars().all()
        return [_enterprise_data_entitlement_row_to_dict(r) for r in rows]

    async def delete_enterprise_data_entitlement(self, entitlement_id: str) -> bool:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(EnterpriseDataEntitlementRow).where(EnterpriseDataEntitlementRow.id == entitlement_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def save_enterprise_records(self, dataset_id: str, rows: list[dict]) -> int:
        async with self.session_factory() as session:
            for row_data in rows:
                session.add(EnterpriseRecordRow(dataset_id=dataset_id, row_data=row_data))
            await session.commit()
        return len(rows)

    async def list_enterprise_records(self, dataset_id: str, *, limit: int = 50) -> list[dict]:
        query = (
            select(EnterpriseRecordRow)
            .where(EnterpriseRecordRow.dataset_id == dataset_id)
            .order_by(EnterpriseRecordRow.ingested_at.desc())
            .limit(limit)
        )
        async with self.session_factory() as session:
            rows = (await session.execute(query)).scalars().all()
        return [_enterprise_record_row_to_dict(r) for r in rows]

    async def record_enterprise_data_event(
        self,
        *,
        source_id: str,
        event_type: str,
        status: str,
        detail: str = "",
        rows_ingested: int | None = None,
        rows_rejected: int | None = None,
        latency_ms: float | None = None,
    ) -> dict:
        row = EnterpriseDataEventRow(
            source_id=source_id,
            event_type=event_type,
            status=status,
            detail=detail,
            rows_ingested=rows_ingested,
            rows_rejected=rows_rejected,
            latency_ms=latency_ms,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _enterprise_data_event_row_to_dict(row)

    async def list_enterprise_data_events(self, source_id: str, *, limit: int = 50) -> list[dict]:
        query = (
            select(EnterpriseDataEventRow)
            .where(EnterpriseDataEventRow.source_id == source_id)
            .order_by(EnterpriseDataEventRow.occurred_at.desc())
            .limit(limit)
        )
        async with self.session_factory() as session:
            rows = (await session.execute(query)).scalars().all()
        return [_enterprise_data_event_row_to_dict(r) for r in rows]

    async def save_committee_decision(
        self, trade_id: UUID, decision: InvestmentCommitteeDecision, *, organization_id: str | None = None
    ) -> None:
        row = CommitteeDecisionRow(
            original_trade_id=str(trade_id),
            organization_id=organization_id,
            original_trade=decision.original_trade.model_dump(mode="json"),
            bull_case=decision.bull_case,
            bear_case=decision.bear_case,
            skeptic_case=decision.skeptic_case,
            data_quality_assessment=decision.data_quality_assessment,
            portfolio_effect=decision.portfolio_effect,
            consensus_score=decision.consensus_score,
            unresolved_questions=decision.unresolved_questions,
            recommended_action=decision.recommended_action.value,
            decided_at=_naive_utc(decision.decided_at),
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    async def save_risk_check(
        self, trade_id: UUID, risk_check: RiskCheckResult, *, organization_id: str | None = None
    ) -> None:
        row = RiskCheckRow(
            check_id=str(risk_check.check_id),
            trade_id=str(trade_id),
            organization_id=organization_id,
            verdict=risk_check.verdict.value,
            rule_results=[r.model_dump(mode="json") for r in risk_check.rule_results],
            governor_version=risk_check.governor_version,
            evaluated_at=_naive_utc(risk_check.evaluated_at),
        )
        async with self.session_factory() as session:
            await session.merge(row)
            await session.commit()

    async def save_approval(
        self,
        *,
        approval_id: UUID,
        trade_id: UUID,
        state: str,
        actions: list[dict],
        updated_at: datetime,
        organization_id: str | None = None,
    ) -> None:
        row = ApprovalRow(
            id=str(approval_id),
            trade_id=str(trade_id),
            organization_id=organization_id,
            state=state,
            actions=actions,
            updated_at=_naive_utc(updated_at),
        )
        async with self.session_factory() as session:
            await session.merge(row)
            await session.commit()

    async def append_decision_journal_entry(self, trade_id: UUID, entry: dict) -> None:
        row = DecisionJournalRow(trade_id=str(trade_id), entry=entry)
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    async def save_post_trade_analysis(self, analysis: PostTradeAnalysis) -> None:
        row = PostTradeAnalysisRow(
            id=str(analysis.id),
            trade_id=str(analysis.trade_id),
            expected_outcome=analysis.expected_outcome,
            actual_outcome=analysis.actual_outcome,
            forecast_error=analysis.forecast_error,
            thesis_accuracy=analysis.thesis_accuracy,
            timing_accuracy=analysis.timing_accuracy,
            risk_accuracy=analysis.risk_accuracy,
            model_contribution=analysis.model_contribution,
            unexpected_events=analysis.unexpected_events,
            lessons=analysis.lessons,
            quadrant=analysis.quadrant.value,
            quant_model_type=analysis.quant_model_type.value if analysis.quant_model_type else None,
            quant_model_version=analysis.quant_model_version,
            quant_predicted_return=analysis.quant_predicted_return,
            quant_forecast_error=analysis.quant_forecast_error,
            quant_up_probability=analysis.quant_up_probability,
            created_at=_naive_utc(analysis.created_at),
        )
        async with self.session_factory() as session:
            await session.merge(row)
            await session.commit()

    async def save_contact_inquiry(
        self,
        *,
        first_name: str,
        last_name: str,
        business_email: str,
        company_name: str,
        job_title: str | None,
        phone: str | None,
        inquiry_type: str,
        message: str,
    ) -> str:
        """Persists a /contact submission. Deliberately takes only plain business-
        inquiry fields — there is no path from here to a `User`/`Organization`/
        `MagicLinkToken` row; this table exists purely for admin visibility into
        inbound inquiries."""
        row = ContactInquiryRow(
            first_name=first_name,
            last_name=last_name,
            business_email=business_email,
            company_name=company_name,
            job_title=job_title,
            phone=phone,
            inquiry_type=inquiry_type,
            message=message,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
        return row.id

    async def list_contact_inquiries(self) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (await session.execute(select(ContactInquiryRow).order_by(ContactInquiryRow.created_at.desc())))
                .scalars()
                .all()
            )
        return [
            {
                "id": r.id,
                "first_name": r.first_name,
                "last_name": r.last_name,
                "business_email": r.business_email,
                "company_name": r.company_name,
                "job_title": r.job_title,
                "phone": r.phone,
                "inquiry_type": r.inquiry_type,
                "message": r.message,
                "created_at": r.created_at,
            }
            for r in rows
        ]

    async def save_risk_limits(self, limits: RiskLimits) -> None:
        row = RiskLimitsRow(
            max_position_size=limits.max_position_size,
            max_risk_per_trade=limits.max_risk_per_trade,
            max_daily_loss=limits.max_daily_loss,
            max_drawdown=limits.max_drawdown,
            max_portfolio_var=limits.max_portfolio_var,
            max_sector_exposure=limits.max_sector_exposure,
            max_contract_exposure=limits.max_contract_exposure,
            max_correlated_exposure=limits.max_correlated_exposure,
            effective_from=_naive_utc(limits.effective_from),
            effective_to=_naive_utc(limits.effective_to),
            set_by_user_id=limits.set_by_user_id,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    # -- hydration --------------------------------------------------------------------

    async def hydrate(self) -> dict:
        """Reloads every persisted object, keyed by trade_id/approval_id (as `str`,
        matching how they're stored) so `AppState` can key its in-memory dicts by
        `UUID(...)` of each key. Returns an empty-but-well-shaped dict when the DB has
        nothing yet (first boot) — safe for `AppState` to iterate unconditionally.
        """
        async with self.session_factory() as session:
            trade_rows = (await session.execute(select(TradeIdeaRow))).scalars().all()
            decision_rows = (await session.execute(select(CommitteeDecisionRow))).scalars().all()
            risk_check_rows = (await session.execute(select(RiskCheckRow))).scalars().all()
            approval_rows = (await session.execute(select(ApprovalRow))).scalars().all()
            journal_rows = (
                (await session.execute(select(DecisionJournalRow).order_by(DecisionJournalRow.created_at)))
                .scalars()
                .all()
            )
            post_trade_rows = (await session.execute(select(PostTradeAnalysisRow))).scalars().all()
            limits_rows = (
                (await session.execute(select(RiskLimitsRow).order_by(RiskLimitsRow.effective_from.desc())))
                .scalars()
                .all()
            )

        trade_ideas: dict[str, TradeIdea] = {}
        forecasts: dict[str, PriceForecast] = {}
        for row in trade_rows:
            trade_ideas[row.trade_id] = TradeIdea(
                trade_id=UUID(row.trade_id),
                strategy=row.strategy,
                instrument=row.instrument,
                instrument_type=row.instrument_type,
                direction=row.direction,
                entry=row.entry,
                target=row.target,
                stop_or_invalidation=row.stop_or_invalidation,
                time_horizon=row.time_horizon,
                expected_return=row.expected_return,
                expected_loss=row.expected_loss,
                probability_success=row.probability_success,
                confidence=row.confidence,
                thesis=row.thesis,
                catalysts=row.catalysts,
                risks=row.risks,
                invalidation_conditions=row.invalidation_conditions,
                supporting_data=row.supporting_data,
                source_citations=row.source_citations,
                created_at=row.created_at,
                expires_at=row.expires_at,
            )
            if row.forecast is not None:
                forecasts[row.trade_id] = PriceForecast.model_validate(row.forecast)

        committee_decisions: dict[str, InvestmentCommitteeDecision] = {}
        for row in decision_rows:
            committee_decisions[row.original_trade_id] = InvestmentCommitteeDecision(
                original_trade=TradeIdea.model_validate(row.original_trade),
                bull_case=row.bull_case,
                bear_case=row.bear_case,
                skeptic_case=row.skeptic_case,
                data_quality_assessment=row.data_quality_assessment,
                portfolio_effect=row.portfolio_effect,
                consensus_score=row.consensus_score,
                unresolved_questions=row.unresolved_questions,
                recommended_action=row.recommended_action,
                decided_at=row.decided_at,
            )

        risk_checks: dict[str, RiskCheckResult] = {}
        for row in risk_check_rows:
            risk_checks[row.trade_id] = RiskCheckResult(
                check_id=UUID(row.check_id),
                trade_id=UUID(row.trade_id),
                verdict=row.verdict,
                rule_results=row.rule_results,
                governor_version=row.governor_version,
                evaluated_at=row.evaluated_at,
            )

        approvals: list[dict] = [
            {
                "id": row.id,
                "trade_id": row.trade_id,
                "state": row.state,
                "actions": row.actions,
                "updated_at": row.updated_at,
            }
            for row in approval_rows
        ]

        decision_journal: dict[str, list[dict]] = {}
        for row in journal_rows:
            decision_journal.setdefault(row.trade_id, []).append(row.entry)

        post_trade_analyses: dict[str, PostTradeAnalysis] = {}
        for row in post_trade_rows:
            post_trade_analyses[row.trade_id] = PostTradeAnalysis(
                id=UUID(row.id),
                trade_id=UUID(row.trade_id),
                expected_outcome=row.expected_outcome,
                actual_outcome=row.actual_outcome,
                forecast_error=row.forecast_error,
                thesis_accuracy=row.thesis_accuracy,
                timing_accuracy=row.timing_accuracy,
                risk_accuracy=row.risk_accuracy,
                model_contribution=row.model_contribution,
                unexpected_events=row.unexpected_events,
                lessons=row.lessons,
                quadrant=row.quadrant,
                quant_model_type=row.quant_model_type,
                quant_model_version=row.quant_model_version,
                quant_predicted_return=row.quant_predicted_return,
                quant_forecast_error=row.quant_forecast_error,
                quant_up_probability=row.quant_up_probability,
                created_at=row.created_at,
            )

        risk_limits: RiskLimits | None = None
        if limits_rows:
            latest = limits_rows[0]
            risk_limits = RiskLimits(
                max_position_size=latest.max_position_size,
                max_risk_per_trade=latest.max_risk_per_trade,
                max_daily_loss=latest.max_daily_loss,
                max_drawdown=latest.max_drawdown,
                max_portfolio_var=latest.max_portfolio_var,
                max_sector_exposure=latest.max_sector_exposure,
                max_contract_exposure=latest.max_contract_exposure,
                max_correlated_exposure=latest.max_correlated_exposure,
                effective_from=latest.effective_from,
                effective_to=latest.effective_to,
                set_by_user_id=latest.set_by_user_id,
            )

        return {
            "trade_ideas": trade_ideas,
            "forecasts": forecasts,
            "committee_decisions": committee_decisions,
            "risk_checks": risk_checks,
            "approvals": approvals,
            "decision_journal": decision_journal,
            "post_trade_analyses": post_trade_analyses,
            "risk_limits": risk_limits,
        }

    # -- Tenant isolation retrofit (docs/alpha-intelligence.md section 11.1, Milestone 9) --

    async def save_model_routing_policy(self, policy: ModelRoutingPolicy) -> None:
        row = ModelRoutingPolicyRow(
            id=str(policy.id),
            organization_id=policy.organization_id,
            data_classification=policy.data_classification.value,
            allow_external_llm_processing=policy.allow_external_llm_processing,
            allowed_provider=policy.allowed_provider,
            allowed_region=policy.allowed_region,
            logging_allowed=policy.logging_allowed,
            created_by=policy.created_by,
            created_at=_naive_utc(policy.created_at),
            updated_at=_naive_utc(policy.updated_at),
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    async def list_model_routing_policies(self, *, organization_id: str | None = None) -> list[dict]:
        """Returns every policy visible to `organization_id` -- its own overrides plus
        every platform-default policy (`organization_id IS NULL`) -- or, when
        `organization_id` is `None`, every platform-default policy alone."""
        query = select(ModelRoutingPolicyRow).order_by(ModelRoutingPolicyRow.created_at.desc())
        if organization_id is not None:
            query = query.where(
                (ModelRoutingPolicyRow.organization_id == organization_id)
                | (ModelRoutingPolicyRow.organization_id.is_(None))
            )
        else:
            query = query.where(ModelRoutingPolicyRow.organization_id.is_(None))
        async with self.session_factory() as session:
            rows = (await session.execute(query)).scalars().all()
        return [_model_routing_policy_row_to_dict(r) for r in rows]

    async def get_model_routing_policy(self, policy_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(ModelRoutingPolicyRow).where(ModelRoutingPolicyRow.id == policy_id))
            ).scalar_one_or_none()
        return _model_routing_policy_row_to_dict(row) if row is not None else None

    async def delete_model_routing_policy(self, policy_id: str) -> bool:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(ModelRoutingPolicyRow).where(ModelRoutingPolicyRow.id == policy_id))
            ).scalar_one_or_none()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def save_retention_policy(self, policy: RetentionPolicy) -> None:
        row = RetentionPolicyRow(
            id=str(policy.id),
            organization_id=policy.organization_id,
            data_classification=policy.data_classification.value,
            retention_days=policy.retention_days,
            created_by=policy.created_by,
            created_at=_naive_utc(policy.created_at),
            updated_at=_naive_utc(policy.updated_at),
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    async def list_retention_policies(self, *, organization_id: str | None = None) -> list[dict]:
        query = select(RetentionPolicyRow).order_by(RetentionPolicyRow.created_at.desc())
        if organization_id is not None:
            query = query.where(
                (RetentionPolicyRow.organization_id == organization_id) | (RetentionPolicyRow.organization_id.is_(None))
            )
        else:
            query = query.where(RetentionPolicyRow.organization_id.is_(None))
        async with self.session_factory() as session:
            rows = (await session.execute(query)).scalars().all()
        return [_retention_policy_row_to_dict(r) for r in rows]

    async def get_retention_policy(self, policy_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(RetentionPolicyRow).where(RetentionPolicyRow.id == policy_id))
            ).scalar_one_or_none()
        return _retention_policy_row_to_dict(row) if row is not None else None

    async def delete_retention_policy(self, policy_id: str) -> bool:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(RetentionPolicyRow).where(RetentionPolicyRow.id == policy_id))
            ).scalar_one_or_none()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def purge_enterprise_records_for_retention(
        self, *, dataset_id: str, cutoff: datetime
    ) -> int:
        """Deletes every `EnterpriseRecordRow` of `dataset_id` ingested before
        `cutoff` -- the mechanical half of `apply_retention_policy`
        (`enterprise_data_service.retention.apply_retention_policy` computes
        `cutoff` from a `RetentionPolicy.retention_days`; this method just performs
        the delete). Returns the number of rows purged."""
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(EnterpriseRecordRow).where(
                        EnterpriseRecordRow.dataset_id == dataset_id, EnterpriseRecordRow.ingested_at < cutoff
                    )
                )
            ).scalars().all()
            for row in rows:
                await session.delete(row)
            await session.commit()
            return len(rows)

    # -- Enterprise Opportunity Engine (docs/alpha-intelligence.md section 11.7, Milestone 10) --

    async def save_enterprise_opportunity(self, opportunity: EnterpriseOpportunity) -> None:
        row = EnterpriseOpportunityRow(
            id=str(opportunity.id),
            organization_id=opportunity.organization_id,
            workspace_id=opportunity.workspace_id,
            opportunity_type=opportunity.opportunity_type.value,
            market=opportunity.market,
            title=opportunity.title,
            summary=opportunity.summary,
            confidence=opportunity.confidence,
            supporting_signal_ids=opportunity.supporting_signal_ids,
            supporting_consensus_id=opportunity.supporting_consensus_id,
            related_dataset_id=opportunity.related_dataset_id,
            related_record_id=opportunity.related_record_id,
            status=opportunity.status.value,
            reviewed_by=opportunity.reviewed_by,
            reviewed_at=_naive_utc(opportunity.reviewed_at) if opportunity.reviewed_at is not None else None,
            created_at=_naive_utc(opportunity.created_at),
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    async def list_enterprise_opportunities(
        self, *, organization_id: str, status: str | None = None, limit: int = 50
    ) -> list[dict]:
        """`organization_id` is required (not optional/nullable) -- unlike every
        Alpha* list method, there is no platform-wide opportunity feed to fall
        back to; a caller always sees only their own organization's rows."""
        query = (
            select(EnterpriseOpportunityRow)
            .where(EnterpriseOpportunityRow.organization_id == organization_id)
            .order_by(EnterpriseOpportunityRow.created_at.desc())
            .limit(limit)
        )
        if status is not None:
            query = query.where(EnterpriseOpportunityRow.status == status)
        async with self.session_factory() as session:
            rows = (await session.execute(query)).scalars().all()
        return [_enterprise_opportunity_row_to_dict(r) for r in rows]

    async def get_enterprise_opportunity(self, opportunity_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(EnterpriseOpportunityRow).where(EnterpriseOpportunityRow.id == opportunity_id)
                )
            ).scalar_one_or_none()
        return _enterprise_opportunity_row_to_dict(row) if row is not None else None

    async def update_enterprise_opportunity_status(
        self, opportunity_id: str, *, status: str, reviewed_by: str, reviewed_at: datetime
    ) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(EnterpriseOpportunityRow).where(EnterpriseOpportunityRow.id == opportunity_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            row.status = status
            row.reviewed_by = reviewed_by
            row.reviewed_at = _naive_utc(reviewed_at)
            await session.commit()
            return _enterprise_opportunity_row_to_dict(row)
