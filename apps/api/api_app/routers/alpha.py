from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from risk_service.scenarios import SCENARIOS
from schemas import LessonProposalStatus, ScenarioDefinition

from ..auth import User
from ..deps import AppStateDep
from ..entitlements import record_is_visible, require_permission, resolve_organization_id, resolve_organization_scope

router = APIRouter(prefix="/alpha", tags=["alpha"])

_RequireAlphaSignals = Depends(require_permission("alpha_signals.view"))
_RequireAlphaImpacts = Depends(require_permission("alpha_impacts.view"))
_RequireAlphaConsensus = Depends(require_permission("alpha_consensus.view"))
_RequireAlphaScenariosView = Depends(require_permission("alpha_scenarios.view"))
_RequireAlphaScenariosRun = Depends(require_permission("alpha_scenarios.run"))
_RequireAlphaMemoryView = Depends(require_permission("alpha_memory.view"))
_RequireAlphaReplay = Depends(require_permission("alpha_replay.view"))
_RequireAlphaBrief = Depends(require_permission("alpha_brief.view"))
_RequireAlphaMemoryReview = Depends(require_permission("alpha_memory.review"))


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
    organization_id, unrestricted = await resolve_organization_scope(user, state)
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    return await state.repo.list_signals(
        organization_id=organization_id,
        platform_only=not unrestricted,
        market=market,
        since=since,
        min_materiality=min_materiality,
        limit=limit,
    )


@router.get("/signals/{signal_id}")
async def get_signal(signal_id: str, state: AppStateDep, user: User = _RequireAlphaSignals) -> dict:
    organization_id, unrestricted = await resolve_organization_scope(user, state)
    signal = await state.repo.get_signal(signal_id, organization_id=organization_id, platform_only=not unrestricted)
    if signal is None:
        raise HTTPException(status_code=404, detail="Signal not found")
    if not record_is_visible(signal.get("organization_id"), organization_id, unrestricted):
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
    organization_id, unrestricted = await resolve_organization_scope(user, state)
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    return await state.repo.list_impact_analyses(
        signal_id=signal_id,
        organization_id=organization_id,
        platform_only=not unrestricted,
        since=since,
        limit=limit,
    )


@router.get("/impacts/{impact_id}")
async def get_impact(impact_id: str, state: AppStateDep, user: User = _RequireAlphaImpacts) -> dict:
    organization_id, unrestricted = await resolve_organization_scope(user, state)
    impact = await state.repo.get_impact_analysis(impact_id, organization_id=organization_id, platform_only=not unrestricted)
    if impact is None:
        raise HTTPException(status_code=404, detail="Impact analysis not found")
    if not record_is_visible(impact.get("organization_id"), organization_id, unrestricted):
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
    organization_id, unrestricted = await resolve_organization_scope(user, state)
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    return await state.repo.list_consensus_views(
        consensus_type=consensus_type,
        organization_id=organization_id,
        platform_only=not unrestricted,
        since=since,
        limit=limit,
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
    organization_id, unrestricted = await resolve_organization_scope(user, state)
    if not record_is_visible(consensus.get("organization_id"), organization_id, unrestricted):
        raise HTTPException(status_code=404, detail="No consensus view found for market")
    return consensus


@router.get("/consensus/by-id/{consensus_id}")
async def get_consensus(consensus_id: str, state: AppStateDep, user: User = _RequireAlphaConsensus) -> dict:
    organization_id, unrestricted = await resolve_organization_scope(user, state)
    consensus = await state.repo.get_consensus_view(
        consensus_id, organization_id=organization_id, platform_only=not unrestricted
    )
    if consensus is None:
        raise HTTPException(status_code=404, detail="Consensus view not found")
    if not record_is_visible(consensus.get("organization_id"), organization_id, unrestricted):
        raise HTTPException(status_code=404, detail="Consensus view not found")
    return consensus


@router.get("/scenarios/library")
async def list_scenario_library(user: User = _RequireAlphaScenariosView) -> list[dict]:
    """The continuously-maintained standing stress-test library
    (`risk_service.scenarios.SCENARIOS`, docs/alpha-intelligence.md section 7) --
    lets a client populate a scenario picker without duplicating the catalog."""
    return [s.__dict__ for s in SCENARIOS]


@router.get("/scenarios/runs")
async def list_scenario_runs(
    state: AppStateDep,
    user: User = _RequireAlphaScenariosView,
    since_hours: int = 24,
    limit: int = 50,
) -> list[dict]:
    organization_id, unrestricted = await resolve_organization_scope(user, state)
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    return await state.repo.list_scenario_runs(
        organization_id=organization_id, platform_only=not unrestricted, since=since, limit=limit
    )


@router.get("/scenarios/runs/{run_id}")
async def get_scenario_run(run_id: str, state: AppStateDep, user: User = _RequireAlphaScenariosView) -> dict:
    organization_id, unrestricted = await resolve_organization_scope(user, state)
    run = await state.repo.get_scenario_run(run_id, organization_id=organization_id, platform_only=not unrestricted)
    if run is None:
        raise HTTPException(status_code=404, detail="Scenario run not found")
    if not record_is_visible(run.get("organization_id"), organization_id, unrestricted):
        raise HTTPException(status_code=404, detail="Scenario run not found")
    return run


@router.post("/scenarios/run")
async def run_alpha_scenario_endpoint(
    definition: ScenarioDefinition, state: AppStateDep, user: User = _RequireAlphaScenariosRun
) -> dict:
    """Composes and runs a (possibly custom) scenario against the paper book --
    AlphaScenario(TM)'s core capability (docs/alpha-intelligence.md section 7).
    `definition.base_scenario_ids` may reference any entry in `GET
    /alpha/scenarios/library`; `definition.variables` stacks additional custom
    shocks on top of those named scenarios."""
    organization_id = await resolve_organization_id(user, state)
    try:
        result = await state.run_alpha_scenario(definition, organization_id=organization_id, requested_by=user.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Unknown base scenario id: {exc}") from exc
    return result.model_dump(mode="json")


@router.post("/scenarios/compare")
async def compare_scenarios(state: AppStateDep, user: User = _RequireAlphaScenariosRun) -> dict:
    """Runs the entire standing stress-test library against the current paper book
    in one pass and ranks the results -- the "base vs. A vs. B vs. C" comparison
    from docs/alpha-intelligence.md section 7."""
    organization_id = await resolve_organization_id(user, state)
    results, comparison = await state.run_alpha_scenario_comparison(
        organization_id=organization_id, requested_by=user.user_id
    )
    return {
        "results": [r.model_dump(mode="json") for r in results],
        "comparison": comparison.model_dump(mode="json"),
    }


class _LessonReviewRequest(BaseModel):
    status: LessonProposalStatus


@router.get("/memory/lessons")
async def list_lesson_proposals(
    state: AppStateDep,
    user: User = _RequireAlphaMemoryView,
    status: LessonProposalStatus | None = None,
    limit: int = 50,
) -> list[dict]:
    """Human-reviewable lesson proposals AlphaMemory(TM) drafted from closed-trade
    outcomes (docs/alpha-intelligence.md section 8), most recent first."""
    organization_id, unrestricted = await resolve_organization_scope(user, state)
    return await state.repo.list_lesson_proposals(
        status=status.value if status is not None else None,
        organization_id=organization_id,
        platform_only=not unrestricted,
        limit=limit,
    )


@router.get("/memory/lessons/{lesson_id}")
async def get_lesson_proposal(lesson_id: str, state: AppStateDep, user: User = _RequireAlphaMemoryView) -> dict:
    organization_id, unrestricted = await resolve_organization_scope(user, state)
    lesson = await state.repo.get_lesson_proposal(lesson_id, organization_id=organization_id, platform_only=not unrestricted)
    if lesson is None:
        raise HTTPException(status_code=404, detail="Lesson proposal not found")
    if not record_is_visible(lesson.get("organization_id"), organization_id, unrestricted):
        raise HTTPException(status_code=404, detail="Lesson proposal not found")
    return lesson


@router.post("/memory/lessons/{lesson_id}/review")
async def review_lesson_proposal(
    lesson_id: str, body: _LessonReviewRequest, state: AppStateDep, user: User = _RequireAlphaMemoryReview
) -> dict:
    """Approves or rejects a lesson proposal (docs/alpha-intelligence.md section 8:
    "lesson proposals are AI-drafted but always human-reviewed... never an
    automatic feedback loop"). This never wires an approved lesson back into any
    production model or threshold -- that remains future work."""
    if body.status == LessonProposalStatus.PENDING:
        raise HTTPException(status_code=400, detail="Cannot review a lesson back to PENDING")
    updated = await state.review_lesson_proposal(lesson_id, status=body.status.value, reviewed_by=user.user_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Lesson proposal not found")
    return updated


@router.get("/memory")
async def list_memory_records(
    state: AppStateDep,
    user: User = _RequireAlphaMemoryView,
    memory_type: str | None = None,
    since_hours: int = 24 * 30,
    limit: int = 50,
) -> list[dict]:
    """AlphaMemory(TM)'s decision records (docs/alpha-intelligence.md section 8),
    most recent first. Defaults to a 30-day window since decision memory is meant
    to be looked back on, not just the last day's activity."""
    organization_id, unrestricted = await resolve_organization_scope(user, state)
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    return await state.repo.list_memory_records(
        memory_type=memory_type,
        organization_id=organization_id,
        platform_only=not unrestricted,
        since=since,
        limit=limit,
    )


@router.get("/memory/{memory_id}")
async def get_memory_record(memory_id: str, state: AppStateDep, user: User = _RequireAlphaMemoryView) -> dict:
    organization_id, unrestricted = await resolve_organization_scope(user, state)
    memory = await state.repo.get_memory_record(memory_id, organization_id=organization_id, platform_only=not unrestricted)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory record not found")
    if not record_is_visible(memory.get("organization_id"), organization_id, unrestricted):
        raise HTTPException(status_code=404, detail="Memory record not found")
    return memory


@router.get("/replay")
async def replay_as_of(
    state: AppStateDep,
    user: User = _RequireAlphaReplay,
    market: str | None = None,
    as_of: datetime | None = None,
) -> dict:
    """AlphaReplay(TM)'s "as known at <timestamp>" reconstruction
    (docs/alpha-intelligence.md section 9): everything the Alpha Intelligence Layer
    itself knew and concluded as of `as_of` (defaults to now), bitemporally
    filtered so nothing from after that moment leaks in. Honest about scope: this
    is always a `CURRENT_MODEL_RETROSPECTIVE` -- a replay of what this
    already-running system recorded at the time -- not a reconstruction of market
    reality from before Milestone 6 shipped; an `as_of` before then simply returns
    empty lists rather than fabricating a plausible-looking history."""
    organization_id, unrestricted = await resolve_organization_scope(user, state)
    resolved_as_of = as_of or datetime.now(timezone.utc)
    result = await state.compute_as_of_replay(
        market=market, as_of=resolved_as_of, organization_id=organization_id, platform_only=not unrestricted
    )
    return result.model_dump(mode="json")


@router.get("/briefs/latest")
async def latest_intelligence_brief(
    state: AppStateDep, user: User = _RequireAlphaBrief, market: str | None = None
) -> dict:
    """The most recently generated Overnight Intelligence Brief
    (docs/alpha-intelligence.md section 10) -- 404 if none has been generated
    yet (a full research cycle hasn't run). Registered before `/briefs/{brief_id}`
    so the literal `latest` isn't swallowed by that parameterized route."""
    organization_id, unrestricted = await resolve_organization_scope(user, state)
    briefs = await state.repo.list_intelligence_briefs(
        market=market, organization_id=organization_id, platform_only=not unrestricted, limit=1
    )
    if not briefs:
        raise HTTPException(status_code=404, detail="No intelligence brief generated yet")
    return briefs[0]


@router.get("/briefs")
async def list_intelligence_briefs(
    state: AppStateDep,
    user: User = _RequireAlphaBrief,
    market: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """History of generated Overnight Intelligence Briefs, most recent first."""
    organization_id, unrestricted = await resolve_organization_scope(user, state)
    return await state.repo.list_intelligence_briefs(
        market=market, organization_id=organization_id, platform_only=not unrestricted, limit=limit
    )


@router.get("/briefs/{brief_id}")
async def get_intelligence_brief(brief_id: str, state: AppStateDep, user: User = _RequireAlphaBrief) -> dict:
    organization_id, unrestricted = await resolve_organization_scope(user, state)
    brief = await state.repo.get_intelligence_brief(brief_id, organization_id=organization_id, platform_only=not unrestricted)
    if brief is None:
        raise HTTPException(status_code=404, detail="Intelligence brief not found")
    if not record_is_visible(brief.get("organization_id"), organization_id, unrestricted):
        raise HTTPException(status_code=404, detail="Intelligence brief not found")
    return brief
