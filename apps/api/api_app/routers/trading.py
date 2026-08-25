from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from ..deps import AppStateDep
from ..explainability import build_explainability

router = APIRouter(tags=["trading"])


@router.get("/trade-ideas")
async def list_trade_ideas(state: AppStateDep, status: str | None = None):
    ideas = list(state.trade_ideas.values())
    if status:
        approvals_by_trade = {a.trade_id: a for a in state.approvals.values()}
        ideas = [t for t in ideas if approvals_by_trade.get(t.trade_id) and approvals_by_trade[t.trade_id].state.value == status]
    return ideas


@router.get("/trade-ideas/{trade_id}")
async def trade_idea_detail(trade_id: UUID, state: AppStateDep):
    trade = state.trade_ideas.get(trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade idea not found")
    committee = state.committee_decisions.get(trade_id)
    risk_check = state.risk_checks.get(trade_id)
    return {
        "trade": trade,
        "committee_decision": committee,
        "risk_check": risk_check,
        "explainability": build_explainability(trade, committee, risk_check),
    }


@router.post("/trade-ideas/{trade_id}/challenge")
async def challenge_trade_idea(trade_id: UUID, state: AppStateDep):
    """'Challenge AI' — re-invokes the Skeptic and Bear agents against the current
    thesis and returns a fresh read without mutating the original committee record."""
    trade = state.trade_ideas.get(trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade idea not found")

    bear_result = await state.investment_committee.bear.run(trade=trade)
    skeptic_result = await state.investment_committee.skeptic.run(trade=trade)

    return {
        "trade_id": trade_id,
        "bear_case": bear_result.outputs.get("case", bear_result.reasoning_summary),
        "skeptic_case": skeptic_result.outputs.get("case", skeptic_result.reasoning_summary),
        "unresolved_questions": skeptic_result.outputs.get("unresolved_questions", []),
    }


@router.get("/committee-decisions/{trade_id}")
async def committee_decision(trade_id: UUID, state: AppStateDep):
    decision = state.committee_decisions.get(trade_id)
    if decision is None:
        raise HTTPException(status_code=404, detail="No committee decision for this trade")
    return decision
