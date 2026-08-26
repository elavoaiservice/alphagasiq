"""Milestone 9: agent versioning + prompt editor + optimization workflow
(spec §§40-41, `docs/agent-governance.md` §§4-5).

**A production agent definition is never overwritten.** Every change to an agent's
instructions, model, or thresholds creates a new `AgentVersionRow` (`packages/db`)
rather than mutating an existing one. "Promoting a version" means the row's status
becomes `PRODUCTION` -- it does not regenerate or replace the agent's Python class;
wiring a per-agent runtime read of its `PRODUCTION` row into `services/agents` is real
follow-up work, not assumed here (see `docs/agent-governance.md` §4).

**No step may be skipped.** The fixed lifecycle DRAFT -> TESTING -> APPROVED ->
PRODUCTION -> (RETIRED | ROLLED_BACK) is enforced by `SqlAppRepository.
transition_agent_version_status` -- there is no "publish directly to production"
affordance, satisfying "no prompt change may automatically bypass evaluation."

Two permission tiers, matching `docs/agent-governance.md` §§3/6 exactly:
- `admin.agent_management` -- draft/list/view/transition versions (the human-driven
  create -> test -> approve -> promote/rollback path).
- `admin.agent_optimization` (`SUPER_ADMIN`-only) -- the Agent Optimization Center's
  entry point, which additionally records a real performance-review snapshot (from
  `AppState.agent_execution_log`) alongside the admin's stated problem/proposed change.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from .. import agent_catalog
from ..audit import record_audit_event
from ..auth import User
from ..deps import AppStateDep
from ..entitlements import require_permission

router = APIRouter(prefix="/admin/agents/{agent_type}/versions", tags=["admin"])
optimization_router = APIRouter(prefix="/admin/agents/{agent_type}/optimization", tags=["admin"])

_RequireAgentManagement = Depends(require_permission("admin.agent_management"))
_RequireAgentOptimization = Depends(require_permission("admin.agent_optimization"))


def _require_versionable(agent_type: str) -> None:
    entry = agent_catalog.catalog_entry(agent_type)
    if not entry["administrable"]:
        detail = (
            "The Risk Governor has no versioning here -- it is not an LLM agent (see "
            "docs/agent-governance.md §1)."
            if agent_type == "RISK_GOVERNOR"
            else "This agent seat is not yet implemented."
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class AgentVersionCreateRequest(BaseModel):
    version: str
    model_provider: str | None = None
    model_name: str | None = None
    system_instructions: str | None = None
    tool_configuration: dict = {}
    data_sources: list = []
    execution_settings: dict = {}
    thresholds: dict = {}
    notes: str | None = None


@router.get("")
async def list_versions(
    agent_type: str, state: AppStateDep, _admin: User = _RequireAgentManagement
) -> list[dict]:
    agent_type = agent_type.upper()
    _require_versionable(agent_type)
    return await state.repo.list_agent_versions(agent_type)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_version(
    agent_type: str, body: AgentVersionCreateRequest, state: AppStateDep, admin: User = _RequireAgentManagement
) -> dict:
    """Creates a new `DRAFT` version -- never edits an existing one (spec §41)."""
    agent_type = agent_type.upper()
    _require_versionable(agent_type)
    return await state.repo.create_agent_version(
        agent_type=agent_type,
        created_by=admin.user_id,
        **body.model_dump(),
    )


@router.get("/production")
async def get_production_version(
    agent_type: str, state: AppStateDep, _admin: User = _RequireAgentManagement
) -> dict:
    agent_type = agent_type.upper()
    _require_versionable(agent_type)
    version = await state.repo.get_production_agent_version(agent_type)
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No PRODUCTION version exists for this agent yet"
        )
    return version


@router.get("/{version_id}")
async def get_version(
    agent_type: str, version_id: str, state: AppStateDep, _admin: User = _RequireAgentManagement
) -> dict:
    agent_type = agent_type.upper()
    _require_versionable(agent_type)
    version = await state.repo.get_agent_version(version_id)
    if version is None or version["agent_type"] != agent_type:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown agent version")
    return version


class AgentVersionTransitionRequest(BaseModel):
    status: str
    evaluation_results: dict | None = None


@router.post("/{version_id}/transition")
async def transition_version(
    agent_type: str,
    version_id: str,
    body: AgentVersionTransitionRequest,
    state: AppStateDep,
    admin: User = _RequireAgentManagement,
) -> dict:
    """Moves a version through the fixed lifecycle -- e.g. `{"status": "TESTING"}` for
    the sandbox-test step, `{"status": "APPROVED", "evaluation_results": {...}}` for
    the human-review/approval gate (spec §41 step 8-9), `{"status": "PRODUCTION"}` to
    promote (auto-retiring the agent's prior PRODUCTION version), or
    `{"status": "ROLLED_BACK"}` to roll back a live PRODUCTION version."""
    agent_type = agent_type.upper()
    _require_versionable(agent_type)
    existing = await state.repo.get_agent_version(version_id)
    if existing is None or existing["agent_type"] != agent_type:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown agent version")
    try:
        updated = await state.repo.transition_agent_version_status(
            version_id, body.status, actor=admin.user_id, evaluation_results=body.evaluation_results
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if body.status in ("PRODUCTION", "ROLLED_BACK"):
        await record_audit_event(
            state,
            actor=admin,
            action=f"agent_version.{'promote' if body.status == 'PRODUCTION' else 'rollback'}",
            resource_type="agent_version",
            resource_id=version_id,
            before=existing,
            after=updated,
        )
    return updated


class OptimizationProposalRequest(BaseModel):
    version: str
    problem_identification: str
    proposed_change: str
    model_provider: str | None = None
    model_name: str | None = None
    system_instructions: str | None = None
    tool_configuration: dict = {}
    data_sources: list = []
    execution_settings: dict = {}
    thresholds: dict = {}


@optimization_router.post("/propose", status_code=status.HTTP_201_CREATED)
async def propose_optimization(
    agent_type: str, body: OptimizationProposalRequest, state: AppStateDep, admin: User = _RequireAgentOptimization
) -> dict:
    """The Agent Optimization Center's entry point (spec §42, steps 1-4): records a
    real performance-review snapshot from `agent_execution_log` alongside the admin's
    stated problem identification and proposed change, then creates a new `DRAFT`
    version -- the same versioning flow as `POST .../versions`, just with the
    stricter `admin.agent_optimization` permission and a mandatory rationale. Steps
    5-12 (sandbox test, evaluation, benchmark comparison, human review, approval,
    deployment, monitoring, rollback) are the same `transition_version` calls used by
    every other version."""
    agent_type = agent_type.upper()
    _require_versionable(agent_type)

    matches = [r for r in state.agent_execution_log if r.agent_type.value == agent_type]
    performance_review = {
        "total_executions": len(matches),
        "success_rate": (
            sum(1 for r in matches if r.status.value == "SUCCESS") / len(matches) if matches else None
        ),
        "average_latency_ms": (
            sum(r.execution_duration_ms for r in matches) / len(matches) if matches else None
        ),
    }
    notes = (
        f"Proposed via Agent Optimization Center by {admin.user_id}.\n"
        f"Problem identification: {body.problem_identification}\n"
        f"Proposed change: {body.proposed_change}\n"
        f"Performance review snapshot at proposal time: {performance_review}"
    )
    return await state.repo.create_agent_version(
        agent_type=agent_type,
        version=body.version,
        model_provider=body.model_provider,
        model_name=body.model_name,
        system_instructions=body.system_instructions,
        tool_configuration=body.tool_configuration,
        data_sources=body.data_sources,
        execution_settings=body.execution_settings,
        thresholds=body.thresholds,
        created_by=admin.user_id,
        notes=notes,
    )
