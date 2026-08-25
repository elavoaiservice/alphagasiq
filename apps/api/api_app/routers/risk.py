from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from risk_service.metrics import PositionSnapshot
from risk_service.scenarios import SCENARIOS, get_scenario, run_scenario
from schemas import RiskLimits

from ..auth import Role, User, require_role
from ..deps import AppStateDep

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get("/portfolio")
async def portfolio_risk(state: AppStateDep):
    summary = state.portfolio_risk_summary()
    return {
        "gross_exposure": summary.gross_exposure,
        "net_exposure": summary.net_exposure,
        "delta": summary.delta,
        "gamma": summary.gamma,
        "vega": summary.vega,
        "unrealized_pnl": summary.unrealized_pnl,
        "realized_pnl": state.paper_adapter.portfolio.total_realized_pnl(),
        "var_95": summary.var_95,
        "expected_shortfall_95": summary.expected_shortfall_95,
        "max_drawdown": summary.max_drawdown,
        "concentration_hhi": summary.concentration_hhi,
        "largest_position_share": summary.largest_position_share,
        "trading_halted": state.trading_halted,
    }


@router.get("/limits", response_model=RiskLimits)
async def get_limits(state: AppStateDep):
    return state.risk_limits


@router.put("/limits", response_model=RiskLimits)
async def put_limits(
    body: RiskLimits,
    state: AppStateDep,
    user: User = Depends(require_role(Role.RISK_MANAGER, Role.ADMIN)),
):
    body.set_by_user_id = user.user_id
    await state.set_risk_limits(body)
    return state.risk_limits


@router.get("/scenarios")
async def list_scenarios():
    return [s.__dict__ for s in SCENARIOS]


@router.post("/scenarios/{scenario_id}/run")
async def run_scenario_endpoint(scenario_id: str, state: AppStateDep):
    try:
        scenario = get_scenario(scenario_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown scenario_id")

    positions = [
        PositionSnapshot(
            instrument=instrument,
            sector="NATURAL_GAS",
            quantity=pos.quantity,
            price=state.mark_price(instrument),
            avg_price=pos.avg_price,
        )
        for instrument, pos in state.paper_adapter.portfolio.positions.items()
    ]
    result = run_scenario(scenario, positions)
    return {
        "scenario": result.scenario.__dict__,
        "portfolio_pnl": result.portfolio_pnl,
        "strategy_pnl": result.strategy_pnl,
        "margin_impact": result.margin_impact,
        "var_impact": result.var_impact,
        "largest_risk_contributor": result.largest_risk_contributor,
    }


@router.get("/governor/checks/{trade_id}")
async def governor_check(trade_id: UUID, state: AppStateDep):
    check = state.risk_checks.get(trade_id)
    if check is None:
        raise HTTPException(status_code=404, detail="No risk check recorded for this trade")
    return check


@router.post("/halt")
async def halt_trading(state: AppStateDep, user: User = Depends(require_role(Role.RISK_MANAGER, Role.ADMIN))):
    state.trading_halted = True
    return {"trading_halted": True}


@router.post("/resume")
async def resume_trading(state: AppStateDep, user: User = Depends(require_role(Role.RISK_MANAGER, Role.ADMIN))):
    state.trading_halted = False
    return {"trading_halted": False}
