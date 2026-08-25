from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from schemas import AgentType

from ..auth import Role, User, require_role
from ..deps import AppStateDep

router = APIRouter(prefix="/agents", tags=["agents"])

# Which AgentType values have a real implementation vs. a defined-but-unbuilt seat.
_IMPLEMENTED = {
    "SUPPLY",
    "DEMAND",
    "STORAGE",
    "WEATHER",
    "PIPELINE",
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

_TEAM = {
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


@router.get("")
async def org_chart(state: AppStateDep):
    last_by_type: dict[str, str] = {}
    for result in state.agent_execution_log:
        last_by_type[result.agent_type.value] = result.status.value

    return [
        {
            "agent_type": t.value,
            "team": _TEAM.get(t.value, "UNASSIGNED"),
            "implemented": t.value in _IMPLEMENTED,
            "last_status": last_by_type.get(t.value, "NEVER_RUN" if t.value in _IMPLEMENTED else "NOT_BUILT"),
        }
        for t in AgentType
    ]


@router.get("/{agent_type}/executions")
async def executions(agent_type: str, state: AppStateDep, limit: int = 20):
    matches = [r for r in state.agent_execution_log if r.agent_type.value == agent_type.upper()]
    return matches[-limit:]


@router.post("/chief-trading/run")
async def run_chief_trading(
    state: AppStateDep,
    user: User = Depends(require_role(Role.RESEARCHER, Role.TRADER, Role.ADMIN)),
):
    current_price = state.market_curve[0].value if state.market_curve else 3.0
    week_balance = sum(b.balance_bcf for b in state.balances[-7:])
    result = await state.chief_trading_agent.run_research_cycle(
        instrument=state.primary_instrument(),
        current_price=current_price,
        balances=state.balances,
        five_year_average_bcf=state.storage_baseline["five_year_average_bcf"],
        last_year_bcf=state.storage_baseline["year_ago_inventory_bcf"],
        as_of=date.today(),
        weather_kwargs=dict(
            model="GFS", run="latest", comparison_run="previous", hdd_run=2.8, hdd_comparison=2.2, cdd_run=4.0, cdd_comparison=4.5
        ),
        market_consensus_bcf=round(week_balance) + 3,
    )
    for res in (result.supply, result.demand, result.storage, result.weather, result.strategy, result.chief):
        if res is not None:
            state.agent_execution_log.append(res)

    new_approvals = []
    for trade in result.trade_ideas:
        approval = await state.submit_trade_idea(trade)
        new_approvals.append(approval)

    return {
        "trade_ideas_generated": len(result.trade_ideas),
        "new_approval_ids": [a.id for a in new_approvals],
        "chief_summary": result.chief.reasoning_summary if result.chief else None,
    }
