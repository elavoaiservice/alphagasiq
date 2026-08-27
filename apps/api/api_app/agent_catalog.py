"""Static AI-agent org-chart catalog (spec §39, `docs/agents.md` §2) -- the single
source of truth for every `AgentType` seat's team, one-line purpose, and business
function, plus how to resolve a *live* agent instance from `AppState` for the seats
that are actually implemented and wired into a running pipeline today.

`IMPLEMENTED_AGENT_TYPES`/`AGENT_TEAM` are the canonical version of the maps
`apps/api/api_app/routers/agents.py` used to define inline for the pre-Milestone-8
org-chart endpoint -- centralized here so the new admin Agent Control Center
(Milestone 8) and that existing endpoint share one definition instead of drifting.
"""

from __future__ import annotations

from typing import Any

# Which AgentType values have a real, tested `BaseAgent` subclass vs. a defined-but-
# unbuilt seat (docs/agents.md §4). This is a fact about the codebase, not aspirational.
IMPLEMENTED_AGENT_TYPES = {
    "SUPPLY",
    "DEMAND",
    "STORAGE",
    "WEATHER",
    "PIPELINE",
    "LNG",
    "POWER_MARKET",
    "NEWS_INTELLIGENCE",
    "FORECASTING",
    "REGIME_DETECTION",
    "RELATIVE_VALUE",
    "BACKTESTING",
    "DIRECTIONAL_STRATEGY",
    "BULL",
    "BEAR",
    "SKEPTIC",
    "DATA_INTEGRITY",
    "PORTFOLIO",
    "RISK_GOVERNOR",
    "CHIEF_TRADING_AGENT",
    "CHIEF_INVESTMENT_AGENT",
}

AGENT_TEAM: dict[str, str] = {
    "SUPPLY": "FUNDAMENTAL_RESEARCH", "DEMAND": "FUNDAMENTAL_RESEARCH", "STORAGE": "FUNDAMENTAL_RESEARCH",
    "WEATHER": "FUNDAMENTAL_RESEARCH", "LNG": "FUNDAMENTAL_RESEARCH", "PIPELINE": "FUNDAMENTAL_RESEARCH",
    "POWER_MARKET": "FUNDAMENTAL_RESEARCH",
    "MARKET_DATA": "MARKET_INTELLIGENCE", "NEWS_INTELLIGENCE": "MARKET_INTELLIGENCE",
    "EVENT_DETECTION": "MARKET_INTELLIGENCE", "SENTIMENT": "MARKET_INTELLIGENCE",
    "FORECASTING": "QUANTITATIVE", "REGIME_DETECTION": "QUANTITATIVE", "RELATIVE_VALUE": "QUANTITATIVE",
    "BACKTESTING": "QUANTITATIVE",
    "DIRECTIONAL_STRATEGY": "STRATEGY", "CALENDAR_SPREAD_STRATEGY": "STRATEGY", "BASIS_STRATEGY": "STRATEGY",
    "STORAGE_ARBITRAGE_STRATEGY": "STRATEGY", "LNG_ARBITRAGE_STRATEGY": "STRATEGY",
    "VOLATILITY_STRATEGY": "STRATEGY", "EVENT_STRATEGY": "STRATEGY",
    "BULL": "INVESTMENT_COMMITTEE", "BEAR": "INVESTMENT_COMMITTEE", "SKEPTIC": "INVESTMENT_COMMITTEE",
    "DATA_INTEGRITY": "INVESTMENT_COMMITTEE", "PORTFOLIO": "INVESTMENT_COMMITTEE",
    "MARKET_RISK": "INDEPENDENT_RISK", "PORTFOLIO_RISK": "INDEPENDENT_RISK", "LIQUIDITY_RISK": "INDEPENDENT_RISK",
    "DATA_RISK": "INDEPENDENT_RISK", "MODEL_RISK": "INDEPENDENT_RISK", "RISK_GOVERNOR": "INDEPENDENT_RISK",
    "CHIEF_TRADING_AGENT": "EXECUTIVE", "CHIEF_INVESTMENT_AGENT": "EXECUTIVE",
}

# One business-function set per team (docs/agent-governance.md §8's five categories).
_TEAM_BUSINESS_FUNCTIONS: dict[str, list[str]] = {
    "EXECUTIVE": ["Trading & Strategy", "Portfolio Management"],
    "FUNDAMENTAL_RESEARCH": ["Market Research"],
    "MARKET_INTELLIGENCE": ["Market Research"],
    "QUANTITATIVE": ["Market Research", "Trading & Strategy"],
    "STRATEGY": ["Trading & Strategy"],
    "INVESTMENT_COMMITTEE": ["Portfolio Management", "Trading & Strategy"],
    "INDEPENDENT_RISK": ["Risk & Governance"],
}

# One-line purpose per seat, condensed from docs/agents.md §2's org chart.
_PURPOSE: dict[str, str] = {
    "SUPPLY": "Lower-48 production, Canadian imports, other supply.",
    "DEMAND": "Res/comm, industrial, Mexico exports, other demand.",
    "STORAGE": "EIA storage nowcast/forecast, 5yr avg/range, EOS projection.",
    "WEATHER": "HDD/CDD, model-run deltas, weather-demand impact.",
    "LNG": "Feedgas, terminal utilization, netback economics.",
    "PIPELINE": "Flows, constraints, outages, digital-twin state.",
    "POWER_MARKET": "ISO/RTO load & generation mix, power burn estimate.",
    "MARKET_DATA": "Curve construction, continuous contracts, basis.",
    "NEWS_INTELLIGENCE": "Ingest -> classify -> structured NewsEvent.",
    "EVENT_DETECTION": "Cross-references news + ops data for confirmed events.",
    "SENTIMENT": "Aggregate directional tone across sources.",
    "FORECASTING": "Multi-horizon price/return forecasts.",
    "REGIME_DETECTION": "Classifies the current market regime.",
    "RELATIVE_VALUE": "Cross-contract/cross-market mispricing signals.",
    "BACKTESTING": "Walk-forward validation of models & strategies.",
    "DIRECTIONAL_STRATEGY": "Directional trade idea generation.",
    "CALENDAR_SPREAD_STRATEGY": "Calendar spread trade idea generation.",
    "BASIS_STRATEGY": "Basis trade idea generation.",
    "STORAGE_ARBITRAGE_STRATEGY": "Storage arbitrage trade idea generation.",
    "LNG_ARBITRAGE_STRATEGY": "LNG arbitrage trade idea generation.",
    "VOLATILITY_STRATEGY": "Volatility trade idea generation.",
    "EVENT_STRATEGY": "Event-driven trade idea generation.",
    "BULL": "Argues the bull case for a proposed trade idea.",
    "BEAR": "Argues the bear case for a proposed trade idea.",
    "SKEPTIC": "Stress-tests the assumptions behind a proposed trade idea.",
    "DATA_INTEGRITY": "Checks the data quality/freshness backing a proposed trade idea.",
    "PORTFOLIO": "Assesses portfolio fit/concentration for a proposed trade idea.",
    "MARKET_RISK": "Market risk oversight (Independent Risk Organization).",
    "PORTFOLIO_RISK": "Portfolio risk oversight (Independent Risk Organization).",
    "LIQUIDITY_RISK": "Liquidity risk oversight (Independent Risk Organization).",
    "DATA_RISK": "Data risk oversight (Independent Risk Organization).",
    "MODEL_RISK": "Model risk oversight (Independent Risk Organization).",
    "RISK_GOVERNOR": "Deterministic, non-LLM, absolute veto over trade risk (docs/risk-framework.md).",
    "CHIEF_TRADING_AGENT": "Orchestrates the research -> strategy -> committee pipeline.",
    "CHIEF_INVESTMENT_AGENT": (
        "Forwards, holds, or kills a committee-reviewed trade idea for human review, subject to the "
        "Risk Governor's verdict."
    ),
}


def catalog_entry(agent_type: str) -> dict[str, Any]:
    return {
        "agent_type": agent_type,
        "team": AGENT_TEAM.get(agent_type, "UNASSIGNED"),
        "business_functions": _TEAM_BUSINESS_FUNCTIONS.get(AGENT_TEAM.get(agent_type, ""), []),
        "purpose": _PURPOSE.get(agent_type, ""),
        "implemented": agent_type in IMPLEMENTED_AGENT_TYPES,
        # The Risk Governor is displayed for visibility only (docs/agent-governance.md §1)
        # -- it is not an LLM agent and carries none of the admin actions in §3.
        "administrable": agent_type in IMPLEMENTED_AGENT_TYPES and agent_type != "RISK_GOVERNOR",
    }


def resolve_agent_instance(state: Any, agent_type: str):
    """Returns the live `BaseAgent` instance backing an implemented, LLM-driven seat,
    or `None` when there isn't a live instance to introspect -- either because the seat
    isn't implemented, or (NEWS_INTELLIGENCE) the class exists and is tested but isn't
    yet wired into any running pipeline (see docs/agents.md §4). Never fabricates a
    stand-in. `RISK_GOVERNOR` is deliberately excluded -- it isn't a `BaseAgent` at all
    (see docs/agent-governance.md §1) and callers should handle it separately."""
    accessors: dict[str, Any] = {
        "SUPPLY": lambda: state.chief_trading_agent.supply_agent,
        "DEMAND": lambda: state.chief_trading_agent.demand_agent,
        "STORAGE": lambda: state.chief_trading_agent.storage_agent,
        "WEATHER": lambda: state.chief_trading_agent.weather_agent,
        "DIRECTIONAL_STRATEGY": lambda: state.chief_trading_agent.strategy_agent,
        "PIPELINE": lambda: state.pipeline_agent,
        "LNG": lambda: state.lng_agent,
        "POWER_MARKET": lambda: state.power_market_agent,
        "FORECASTING": lambda: state.forecasting_agent,
        "REGIME_DETECTION": lambda: state.regime_detection_agent,
        "RELATIVE_VALUE": lambda: state.relative_value_agent,
        "BACKTESTING": lambda: state.backtesting_agent,
        "BULL": lambda: state.investment_committee.bull,
        "BEAR": lambda: state.investment_committee.bear,
        "SKEPTIC": lambda: state.investment_committee.skeptic,
        "DATA_INTEGRITY": lambda: state.investment_committee.data_integrity,
        "PORTFOLIO": lambda: state.investment_committee.portfolio,
        "CHIEF_TRADING_AGENT": lambda: state.chief_trading_agent,
        "CHIEF_INVESTMENT_AGENT": lambda: state.chief_investment_agent,
    }
    accessor = accessors.get(agent_type)
    return accessor() if accessor is not None else None
