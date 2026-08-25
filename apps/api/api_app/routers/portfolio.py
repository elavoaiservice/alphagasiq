from __future__ import annotations

from fastapi import APIRouter

from ..deps import AppStateDep

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/positions")
async def positions(state: AppStateDep):
    return [
        {
            "instrument": p.instrument,
            "quantity": p.quantity,
            "avg_price": p.avg_price,
            "mark_price": state.mark_price(p.instrument),
            "unrealized_pnl": round(p.unrealized_pnl(state.mark_price(p.instrument)), 2),
            "realized_pnl": p.realized_pnl,
            "is_simulated": True,
        }
        for p in state.paper_adapter.portfolio.positions.values()
    ]


@router.get("/pnl")
async def pnl(state: AppStateDep):
    marks = {i: state.mark_price(i) for i in state.paper_adapter.portfolio.positions}
    return {
        "realized_pnl": state.paper_adapter.portfolio.total_realized_pnl(),
        "unrealized_pnl": state.paper_adapter.portfolio.total_unrealized_pnl(marks),
        "is_simulated": True,
    }


@router.get("/paper-orders")
async def paper_orders(state: AppStateDep):
    return state.paper_adapter.portfolio.fills
