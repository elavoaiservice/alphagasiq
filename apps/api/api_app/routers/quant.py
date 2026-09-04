from __future__ import annotations

from fastapi import APIRouter, HTTPException
from quant_service.models import all_model_status

from ..deps import AppStateDep

router = APIRouter(prefix="/quant", tags=["quant"])


@router.get("/forecast")
async def latest_forecast(state: AppStateDep):
    if state.latest_forecast is None:
        raise HTTPException(status_code=503, detail="No forecast generated yet")
    return {**state.latest_forecast.model_dump(mode="json"), "classification": "SIMULATED"}


@router.get("/regime")
async def latest_regime(state: AppStateDep):
    if state.latest_regime is None:
        raise HTTPException(status_code=503, detail="No regime classification generated yet")
    return {**state.latest_regime.model_dump(mode="json"), "classification": "SIMULATED"}


@router.get("/relative-value")
async def latest_relative_value(state: AppStateDep):
    if state.latest_relative_value is None:
        raise HTTPException(status_code=503, detail="No relative value signals generated yet")
    return {**state.latest_relative_value, "classification": "SIMULATED"}


@router.get("/backtest")
async def latest_backtest(state: AppStateDep):
    if not state.latest_backtests:
        raise HTTPException(status_code=503, detail="No backtest results generated yet")
    return {
        "results_by_model": {name: r.model_dump(mode="json") for name, r in state.latest_backtests.items()},
        "classification": "SIMULATED",
    }


@router.get("/models")
async def model_registry_status():
    """Every model type docs/architecture.md names (linear regression, ARIMA, VAR,
    state-space, Random Forest, XGBoost, LightGBM, TFT, LSTM), with an honest
    implemented/not-implemented flag — mirrors `/agents`'s org-chart honesty."""
    return all_model_status()
