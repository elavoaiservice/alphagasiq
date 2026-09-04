from __future__ import annotations

from datetime import datetime, timezone

from config import branding
from fastapi import APIRouter

from ..deps import AppStateDep

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status")
async def status(state: AppStateDep):
    return {
        "product_name": branding.FULL_NAME,
        "environment": state.settings.environment,
        "time": datetime.now(timezone.utc),
        "trading_halted": state.trading_halted,
        "event_bus_impl": state.settings.event_bus_impl,
        "services": {
            "fundamentals": "ok",
            "agents": "ok",
            "risk_governor": "ok",
            "paper_execution": "ok",
        },
        "counts": {
            "trade_ideas": len(state.trade_ideas),
            "approvals": len(state.approvals),
            "news_events": len(state.news_events),
        },
    }


@router.get("/providers")
async def providers(state: AppStateDep):
    health = await state.providers.health_snapshot()
    return [
        {
            "provider_id": h.provider_id,
            "status": h.status,
            "detail": h.detail,
            "checked_at": h.checked_at,
            "classification": state.providers.get(h.provider_id).classification,
        }
        for h in health
    ]


@router.get("/freshness")
async def freshness(state: AppStateDep):
    now = datetime.now(timezone.utc)
    out = []
    for p in state.providers.all():
        out.append(
            {
                "provider_id": p.provider_id,
                "classification": p.classification,
                "freshness_sla_seconds": p.freshness_sla_seconds,
            }
        )
    return {"as_of": now, "providers": out}
