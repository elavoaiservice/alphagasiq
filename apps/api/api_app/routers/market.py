from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..deps import AppStateDep

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/curve/{instrument}")
async def curve(instrument: str, state: AppStateDep):
    """`instrument` is accepted for URL/REST symmetry with the API spec, but the
    platform currently maintains a single continuous Henry Hub curve (M1-M36), so the
    response always reports the real M1 contract symbol (`state.primary_instrument()`)
    rather than echoing back whatever string was passed in the path — that symbol
    rolls month-to-month and is what paper orders actually execute against (see
    `AppState.primary_instrument`)."""
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
    return {
        "instrument": state.primary_instrument(),
        "points": points,
        "as_of": state.market_curve[0].observation_time if points else None,
    }


@router.get("/summary")
async def summary(state: AppStateDep):
    if not state.market_curve:
        raise HTTPException(status_code=503, detail="Market data not yet seeded")
    m1 = state.market_curve[0]
    m2 = state.market_curve[1] if len(state.market_curve) > 1 else m1
    strip = [o.value for o in state.market_curve[:12]]
    portfolio = state.portfolio_risk_summary()
    # Phase 1 free-data-feed integration, Round 2 (spec section 26): replaces the
    # previous `ai_market_bias` field, which was never actually AI-decided -- just a
    # raw count of LONG vs. SHORT trade ideas -- with the real, deterministic,
    # weighted `MarketBiasResult` (`alpha_service.compute_market_bias`), the single
    # Market Bias concept this platform now has (see `GET /alpha/market-bias` for
    # the full driver breakdown this summary's `market_bias` label summarizes).
    bias = await state.compute_market_bias()
    return {
        "hh_m1": m1.value,
        "hh_m1_symbol": m1.symbol,
        "hh_m2": m2.value,
        "twelve_month_strip_avg": round(sum(strip) / len(strip), 3) if strip else None,
        "nav": 100_000 + portfolio.unrealized_pnl,
        "daily_pnl": portfolio.unrealized_pnl,
        "unrealized_pnl": portfolio.unrealized_pnl,
        "var_95": portfolio.var_95,
        "market_bias": bias.label.value,
        "market_bias_score": bias.score,
        "classification": m1.source_type,
        "as_of": m1.observation_time,
    }


@router.get("/ttf")
async def ttf(state: AppStateDep):
    if not state.ttf_price:
        raise HTTPException(status_code=503, detail="TTF data not yet seeded")
    o = state.ttf_price[0]
    return {"price": o.value, "unit": o.unit, "as_of": o.observation_time, "classification": o.source_type}
