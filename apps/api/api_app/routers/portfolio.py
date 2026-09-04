"""Portfolio Analytics is one of spec §24's `security_sensitive` features and one of
its own explicit chat-authorization examples ("User without portfolio access: Cannot
retrieve restricted portfolio data") — the same `portfolio_analytics` feature gate
applies here at the underlying data API, per spec §25 "Both UI and backend APIs must
enforce entitlements".
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..deps import AppStateDep
from ..entitlements import require_feature

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

_RequirePortfolioAnalytics = Depends(require_feature("portfolio_analytics"))


@router.get("/positions")
async def positions(state: AppStateDep, _user=_RequirePortfolioAnalytics):
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
async def pnl(state: AppStateDep, _user=_RequirePortfolioAnalytics):
    marks = {i: state.mark_price(i) for i in state.paper_adapter.portfolio.positions}
    return {
        "realized_pnl": state.paper_adapter.portfolio.total_realized_pnl(),
        "unrealized_pnl": state.paper_adapter.portfolio.total_unrealized_pnl(marks),
        "is_simulated": True,
    }


@router.get("/paper-orders")
async def paper_orders(state: AppStateDep, _user=_RequirePortfolioAnalytics):
    return state.paper_adapter.portfolio.fills
