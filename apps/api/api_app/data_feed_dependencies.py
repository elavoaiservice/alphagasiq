"""Static data-feed → agent → business-function dependency map (spec §37). Reflects
this platform's real agent org chart (`docs/agents.md` §2) — every downstream agent
named here actually exists and actually consumes that provider's classification of
data, so this is a documented fact about the architecture, not a fabricated graph.

Business function categories are the same five spec §50 / `docs/agent-governance.md`
§2 already use: Market Research, Trading & Strategy, Physical Optimization, Portfolio
Management, Risk & Governance.
"""

from __future__ import annotations

_DEPENDENCIES: dict[str, dict[str, list[str]]] = {
    "eia": {
        "affected_agents": ["Storage Agent", "Supply Agent", "Demand Agent", "Forecasting Agent"],
        "affected_business_functions": ["Market Research", "Trading & Strategy"],
        "chain": [
            "EIA",
            "Storage Agent",
            "Forecasting Agent",
            "Directional Strategy Agent",
            "Chief Trading Agent",
            "Trade Recommendation",
        ],
    },
    "noaa_nws": {
        "affected_agents": ["Weather Agent", "Demand Agent", "Storage Agent", "Forecasting Agent"],
        "affected_business_functions": ["Market Research", "Trading & Strategy"],
        "chain": [
            "NOAA",
            "Weather Agent",
            "Demand Agent",
            "Storage Agent",
            "Forecasting Agent",
            "Directional Strategy Agent",
            "Chief Trading Agent",
            "Trade Recommendation",
        ],
    },
    "iso_rto_public": {
        "affected_agents": ["Power Market Agent", "Demand Agent", "Forecasting Agent"],
        "affected_business_functions": ["Market Research", "Physical Optimization"],
        "chain": ["ISO/RTO", "Power Market Agent", "Demand Agent", "Forecasting Agent", "Chief Trading Agent"],
    },
    "sec_edgar": {
        "affected_agents": ["News Intelligence Agent", "Event Detection Agent", "Sentiment Agent"],
        "affected_business_functions": ["Market Research"],
        "chain": ["SEC EDGAR", "News Intelligence Agent", "Event Detection Agent", "Chief Trading Agent"],
    },
    "rss_news": {
        "affected_agents": ["News Intelligence Agent", "Event Detection Agent", "Sentiment Agent"],
        "affected_business_functions": ["Market Research"],
        "chain": ["News RSS", "News Intelligence Agent", "Sentiment Agent", "Chief Trading Agent"],
    },
    "mock_news": {
        "affected_agents": ["News Intelligence Agent", "Event Detection Agent", "Sentiment Agent"],
        "affected_business_functions": ["Market Research"],
        "chain": ["Simulated News", "News Intelligence Agent", "Sentiment Agent", "Chief Trading Agent"],
    },
    "licensed_news": {
        "affected_agents": ["News Intelligence Agent", "Event Detection Agent", "Sentiment Agent"],
        "affected_business_functions": ["Market Research"],
        "chain": ["Licensed News", "News Intelligence Agent", "Sentiment Agent", "Chief Trading Agent"],
    },
    "mock_cme": {
        "affected_agents": ["Market Data Agent", "Forecasting Agent", "Regime Detection Agent", "Relative Value Agent"],
        "affected_business_functions": ["Trading & Strategy", "Portfolio Management"],
        "chain": ["CME (simulated)", "Market Data Agent", "Forecasting Agent", "Strategy Team", "Chief Trading Agent"],
    },
    "mock_ice": {
        "affected_agents": ["Market Data Agent", "Forecasting Agent", "Regime Detection Agent", "Relative Value Agent"],
        "affected_business_functions": ["Trading & Strategy", "Portfolio Management"],
        "chain": ["ICE (simulated)", "Market Data Agent", "Forecasting Agent", "Strategy Team", "Chief Trading Agent"],
    },
    "cme_live": {
        "affected_agents": ["Market Data Agent", "Forecasting Agent", "Regime Detection Agent", "Relative Value Agent"],
        "affected_business_functions": ["Trading & Strategy", "Portfolio Management"],
        "chain": ["CME", "Market Data Agent", "Forecasting Agent", "Strategy Team", "Chief Trading Agent"],
    },
    "ice_live": {
        "affected_agents": ["Market Data Agent", "Forecasting Agent", "Regime Detection Agent", "Relative Value Agent"],
        "affected_business_functions": ["Trading & Strategy", "Portfolio Management"],
        "chain": ["ICE", "Market Data Agent", "Forecasting Agent", "Strategy Team", "Chief Trading Agent"],
    },
    "ferc_public": {
        "affected_agents": ["Pipeline Agent", "Storage Agent", "Forecasting Agent"],
        "affected_business_functions": ["Market Research", "Physical Optimization"],
        "chain": ["FERC eLibrary", "Pipeline Agent", "Storage Agent", "Forecasting Agent", "Chief Trading Agent"],
    },
    "pipeline_bulletin_board": {
        "affected_agents": ["Pipeline Agent", "Storage Agent", "Forecasting Agent"],
        "affected_business_functions": ["Market Research", "Physical Optimization"],
        "chain": [
            "Pipeline Bulletin Boards",
            "Pipeline Agent",
            "Storage Agent",
            "Forecasting Agent",
            "Chief Trading Agent",
        ],
    },
}

_DEFAULT_DEPENDENCY: dict[str, list[str]] = {
    "affected_agents": [],
    "affected_business_functions": [],
    "chain": [],
}


def get_dependencies(provider_id: str) -> dict[str, list[str]]:
    return _DEPENDENCIES.get(provider_id, _DEFAULT_DEPENDENCY)


def full_dependency_map() -> dict[str, dict[str, list[str]]]:
    return dict(_DEPENDENCIES)
