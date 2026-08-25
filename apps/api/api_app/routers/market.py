from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..deps import AppStateDep

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/curve/{instrument}")
async def curve(instrument: str, state: AppStateDep):
    points = [
        {
            "symbol": o.symbol,
            "curve_position": o.metadata.get("curve_position"),
            "price": o.value,
            "unit": o.unit,
            "observation_time": o.observation_time,
            "source": o.source,
            "classification": o.source_type,
        }
        for o in state.market_curve
    ]
    return {"instrument": instrument, "points": points, "as_of": state.market_curve[0].observation_time if points else None}


@router.get("/summary")
async def summary(state: AppStateDep):
    if not state.market_curve:
        raise HTTPException(status_code=503, detail="Market data not yet seeded")
    m1 = state.market_curve[0]
    m2 = state.market_curve[1] if len(state.market_curve) > 1 else m1
    strip = [o.value for o in state.market_curve[:12]]
    portfolio = state.portfolio_risk_summary()
    return {
        "hh_m1": m1.value,
        "hh_m1_symbol": m1.symbol,
        "hh_m2": m2.value,
        "twelve_month_strip_avg": round(sum(strip) / len(strip), 3) if strip else None,
        "nav": 100_000 + portfolio.unrealized_pnl,
        "daily_pnl": portfolio.unrealized_pnl,
        "unrealized_pnl": portfolio.unrealized_pnl,
        "var_95": portfolio.var_95,
        "ai_market_bias": _bias_from_trade_ideas(state),
        "classification": m1.source_type,
        "as_of": m1.observation_time,
    }


def _bias_from_trade_ideas(state) -> str:
    if not state.trade_ideas:
        return "NEUTRAL"
    longs = sum(1 for t in state.trade_ideas.values() if t.direction.value == "LONG")
    shorts = sum(1 for t in state.trade_ideas.values() if t.direction.value == "SHORT")
    if longs > shorts:
        return "BULLISH"
    if shorts > longs:
        return "BEARISH"
    return "NEUTRAL"


@router.get("/ttf")
async def ttf(state: AppStateDep):
    if not state.ttf_price:
        raise HTTPException(status_code=503, detail="TTF data not yet seeded")
    o = state.ttf_price[0]
    return {"price": o.value, "unit": o.unit, "as_of": o.observation_time, "classification": o.source_type}
