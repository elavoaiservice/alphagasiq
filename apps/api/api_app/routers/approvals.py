from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from schemas import ApprovalAction, ApprovalState

from ..auth import Role, User, require_role
from ..deps import AppStateDep
from ..models import ApprovalActionRecord

router = APIRouter(prefix="/approvals", tags=["approvals"])

_TRANSITIONS: dict[ApprovalAction, ApprovalState] = {
    ApprovalAction.APPROVE: ApprovalState.APPROVED_FOR_PAPER_TRADING,
    ApprovalAction.REJECT: ApprovalState.REJECTED,
    ApprovalAction.MODIFY: ApprovalState.HUMAN_REVIEW,
    ApprovalAction.CHALLENGE: ApprovalState.HUMAN_REVIEW,
    ApprovalAction.REQUEST_MORE_ANALYSIS: ApprovalState.AI_REVIEW,
    ApprovalAction.REDUCE_POSITION: ApprovalState.HUMAN_REVIEW,
    ApprovalAction.CHANGE_INVALIDATION_CONDITION: ApprovalState.HUMAN_REVIEW,
}


class ApprovalActionRequest(BaseModel):
    action: ApprovalAction
    payload: dict[str, Any] = {}


@router.get("")
async def list_approvals(state: AppStateDep, approval_state: str | None = None):
    items = list(state.approvals.values())
    if approval_state:
        items = [a for a in items if a.state.value == approval_state]
    return items


@router.post("/{approval_id}/action")
async def act_on_approval(
    approval_id: UUID,
    body: ApprovalActionRequest,
    state: AppStateDep,
    user: User = Depends(require_role(Role.TRADER, Role.RISK_MANAGER, Role.ADMIN)),
):
    approval = state.approvals.get(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")

    if approval.state in (ApprovalState.REJECTED, ApprovalState.EXPIRED, ApprovalState.CLOSED):
        raise HTTPException(status_code=409, detail=f"Approval is terminal ({approval.state.value})")

    if body.action == ApprovalAction.APPROVE and approval.state == ApprovalState.RISK_REVIEW:
        raise HTTPException(
            status_code=409,
            detail="Cannot approve: Risk Governor has not cleared this trade (see /risk/governor/checks/{trade_id}).",
        )

    approval.actions.append(ApprovalActionRecord(action=body.action, payload=body.payload, user_id=user.user_id))
    approval.state = _TRANSITIONS[body.action]

    if approval.state == ApprovalState.APPROVED_FOR_PAPER_TRADING:
        trade = state.trade_ideas[approval.trade_id]
        from paper_execution_service import OrderSide, OrderType, PaperOrder

        order = PaperOrder(
            trade_id=trade.trade_id,
            instrument=trade.instrument,
            order_type=OrderType.MARKET,
            side=OrderSide.BUY if trade.direction.value == "LONG" else OrderSide.SELL,
            quantity=body.payload.get("quantity", 10),
        )
        market_price = state.mark_price(trade.instrument)
        await state.paper_adapter.submit_order(order, market_price)
        approval.state = ApprovalState.EXECUTED_SIMULATION

    await state.persist_approval(approval)
    return approval
