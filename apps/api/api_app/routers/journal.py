from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from ..deps import AppStateDep

router = APIRouter(tags=["journal"])


@router.get("/journal/{trade_id}")
async def journal_entry(trade_id: UUID, state: AppStateDep):
    entries = state.decision_journal.get(trade_id)
    if not entries:
        raise HTTPException(status_code=404, detail="No decision journal entries for this trade")
    return {"trade_id": trade_id, "entries": entries}


@router.get("/post-trade/{trade_id}")
async def post_trade_analysis(trade_id: UUID, state: AppStateDep):
    """Post-trade analysis is generated once a position closes (Milestone 11). Until
    then this reports the position as still open rather than fabricating an outcome."""
    trade = state.trade_ideas.get(trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade idea not found")

    approvals = [a for a in state.approvals.values() if a.trade_id == trade_id]
    closed = any(a.state.value == "CLOSED" for a in approvals)
    if not closed:
        return {
            "trade_id": trade_id,
            "status": "OPEN",
            "detail": "Position has not closed yet; post-trade analysis is generated on close.",
        }
    raise HTTPException(status_code=501, detail="Post-trade analysis generation not yet implemented (Milestone 11)")
