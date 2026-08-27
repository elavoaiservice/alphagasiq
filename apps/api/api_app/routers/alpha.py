from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from ..auth import User
from ..deps import AppStateDep
from ..entitlements import require_permission, resolve_organization_id

router = APIRouter(prefix="/alpha", tags=["alpha"])

_RequireAlphaSignals = Depends(require_permission("alpha_signals.view"))


@router.get("/signals")
async def list_signals(
    state: AppStateDep,
    user: User = _RequireAlphaSignals,
    market: str | None = None,
    since_hours: int = 24,
    min_materiality: float = 0.0,
    limit: int = 50,
) -> list[dict]:
    """AlphaSignal(TM)'s ranked feed (docs/alpha-intelligence.md section 2) --
    highest-materiality signals first, then most recent. Includes both the
    requester's organization-scoped signals and every platform-wide signal
    (`organization_id IS NULL`, the only kind Milestone 1's detector produces)."""
    organization_id = await resolve_organization_id(user, state)
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    return await state.repo.list_signals(
        organization_id=organization_id,
        market=market,
        since=since,
        min_materiality=min_materiality,
        limit=limit,
    )


@router.get("/signals/{signal_id}")
async def get_signal(signal_id: str, state: AppStateDep, user: User = _RequireAlphaSignals) -> dict:
    signal = await state.repo.get_signal(signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="Signal not found")
    return signal
