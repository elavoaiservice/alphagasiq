from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from ..auth import User
from ..deps import AppStateDep
from ..entitlements import require_permission, resolve_organization_id

router = APIRouter(prefix="/alpha", tags=["alpha"])

_RequireAlphaSignals = Depends(require_permission("alpha_signals.view"))
_RequireAlphaImpacts = Depends(require_permission("alpha_impacts.view"))
_RequireAlphaConsensus = Depends(require_permission("alpha_consensus.view"))


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


@router.get("/impacts")
async def list_impacts(
    state: AppStateDep,
    user: User = _RequireAlphaImpacts,
    signal_id: str | None = None,
    since_hours: int = 24,
    limit: int = 50,
) -> list[dict]:
    """AlphaImpact(TM)'s causal-chain analyses (docs/alpha-intelligence.md section 5),
    most recent first. Includes both the requester's organization-scoped analyses and
    every platform-wide one (`organization_id IS NULL`, the only kind Milestone 2's
    engine produces)."""
    organization_id = await resolve_organization_id(user, state)
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    return await state.repo.list_impact_analyses(
        signal_id=signal_id, organization_id=organization_id, since=since, limit=limit
    )


@router.get("/impacts/{impact_id}")
async def get_impact(impact_id: str, state: AppStateDep, user: User = _RequireAlphaImpacts) -> dict:
    impact = await state.repo.get_impact_analysis(impact_id)
    if impact is None:
        raise HTTPException(status_code=404, detail="Impact analysis not found")
    return impact


@router.get("/consensus")
async def list_consensus(
    state: AppStateDep,
    user: User = _RequireAlphaConsensus,
    consensus_type: str | None = None,
    since_hours: int = 24,
    limit: int = 50,
) -> list[dict]:
    """AlphaConsensus(TM)'s dynamically-weighted agent views (docs/alpha-intelligence.md
    section 6), most recent first. Includes both the requester's organization-scoped
    views and every platform-wide one (`organization_id IS NULL`, the only kind
    Milestone 3's engine produces)."""
    organization_id = await resolve_organization_id(user, state)
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    return await state.repo.list_consensus_views(
        consensus_type=consensus_type, organization_id=organization_id, since=since, limit=limit
    )


@router.get("/consensus/{market}")
async def get_consensus_for_market(
    market: str, state: AppStateDep, user: User = _RequireAlphaConsensus
) -> dict:
    """Latest consensus view for a given market (e.g. `HENRY_HUB`) -- the flagship
    "AlphaConsensus vs. Market Consensus" comparison from docs/alpha-intelligence.md
    section 6."""
    consensus = await state.repo.get_latest_consensus_view_for_market(market)
    if consensus is None:
        raise HTTPException(status_code=404, detail="No consensus view found for market")
    return consensus


@router.get("/consensus/by-id/{consensus_id}")
async def get_consensus(consensus_id: str, state: AppStateDep, user: User = _RequireAlphaConsensus) -> dict:
    consensus = await state.repo.get_consensus_view(consensus_id)
    if consensus is None:
        raise HTTPException(status_code=404, detail="Consensus view not found")
    return consensus
