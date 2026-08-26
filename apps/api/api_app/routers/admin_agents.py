"""Milestone 8: AI Agent Control Center (spec §39, `docs/agent-governance.md` §§2-3).

An admin-only view of every seat in the platform's real multi-agent org chart
(`docs/agents.md` §2), merging the static catalog (team/purpose/business functions/
implemented flag, `apps/api/api_app/agent_catalog.py`) with each implemented agent's
live model/version info, real execution statistics from `AppState.agent_execution_log`,
and its admin-editable operational config (`AgentConfigRow`, `packages/db`).

**The Risk Governor is displayed for visibility only.** It has no `AgentConfigRow`, no
status to PATCH, and no manual-run action here -- see `docs/agent-governance.md` §1 and
`agent_catalog.catalog_entry`'s `administrable` flag, which is `False` only for it.

**Direct untested production replacement is never permitted.** Every action this router
exposes is enable/disable/pause/resume of an *already-approved* agent, or a manual run of
its already-approved logic -- never an edit to its prompt/model/instructions. That flow
(draft -> test -> evaluate -> approve -> publish -> rollback) is Milestone 9's versioning
system, not this one.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from schemas import AgentType

from .. import agent_catalog
from ..audit import record_audit_event
from ..auth import User
from ..deps import AppStateDep
from ..entitlements import require_permission

router = APIRouter(prefix="/admin/agents", tags=["admin"])

_RequireAgentManagement = Depends(require_permission("admin.agent_management"))

_ADMIN_SETTABLE_STATUSES = {"ACTIVE", "PAUSED", "DISABLED", "TESTING"}


def _execution_stats(state: AppStateDep, agent_type: str) -> dict:
    matches = [r for r in state.agent_execution_log if r.agent_type.value == agent_type]
    if not matches:
        return {
            "total_executions": 0,
            "last_execution_time": None,
            "last_status": None,
            "average_latency_ms": None,
            "success_rate": None,
            "error_rate": None,
        }
    ordered = sorted(matches, key=lambda r: r.last_execution_time)
    successes = sum(1 for r in matches if r.status.value == "SUCCESS")
    errors = sum(1 for r in matches if r.status.value == "FAILED")
    return {
        "total_executions": len(matches),
        "last_execution_time": ordered[-1].last_execution_time,
        "last_status": ordered[-1].status.value,
        "average_latency_ms": sum(r.execution_duration_ms for r in matches) / len(matches),
        "success_rate": successes / len(matches),
        "error_rate": errors / len(matches),
    }


def _live_agent_info(state: AppStateDep, agent_type: str) -> dict:
    if agent_type == "RISK_GOVERNOR":
        return {"agent_id": None, "version": state.risk_governor.version, "model_provider": None, "model": None}
    instance = agent_catalog.resolve_agent_instance(state, agent_type)
    if instance is None:
        return {"agent_id": None, "version": None, "model_provider": None, "model": None}
    return {
        "agent_id": instance.agent_id,
        "version": instance.version,
        "model_provider": type(instance.llm).__name__,
        "model": getattr(instance.llm, "model", None),
    }


def _merge_agent_view(state: AppStateDep, agent_type: str, config: dict | None) -> dict:
    entry = agent_catalog.catalog_entry(agent_type)
    entry.update(_live_agent_info(state, agent_type))
    entry.update(_execution_stats(state, agent_type))
    entry.update(
        {
            "status": config["status"] if config is not None else None,
            "confidence_threshold": config["confidence_threshold"] if config is not None else None,
            "alert_threshold": config["alert_threshold"] if config is not None else None,
            "escalation_threshold": config["escalation_threshold"] if config is not None else None,
            "notes": config["notes"] if config is not None else None,
            "updated_by": config["updated_by"] if config is not None else None,
            "updated_at": config["updated_at"] if config is not None else None,
        }
    )
    return entry


@router.get("")
async def list_agents(state: AppStateDep, _admin: User = _RequireAgentManagement) -> list[dict]:
    configs_by_type = {c["agent_type"]: c for c in await state.repo.list_agent_configs()}
    return [_merge_agent_view(state, t.value, configs_by_type.get(t.value)) for t in AgentType]


@router.get("/{agent_type}")
async def get_agent(agent_type: str, state: AppStateDep, _admin: User = _RequireAgentManagement) -> dict:
    agent_type = agent_type.upper()
    if agent_type not in {t.value for t in AgentType}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown agent type")
    config = await state.repo.get_agent_config(agent_type)
    view = _merge_agent_view(state, agent_type, config)
    matches = [r for r in state.agent_execution_log if r.agent_type.value == agent_type]
    ordered = sorted(matches, key=lambda r: r.last_execution_time, reverse=True)
    view["recent_executions"] = ordered[:20]
    view["recent_errors"] = [
        {"execution_id": str(r.execution_id), "occurred_at": r.last_execution_time, "errors": r.errors}
        for r in ordered
        if r.errors
    ][:20]
    return view


class AgentConfigUpdateRequest(BaseModel):
    status: str | None = None
    confidence_threshold: float | None = None
    alert_threshold: float | None = None
    escalation_threshold: float | None = None
    notes: str | None = None


@router.patch("/{agent_type}")
async def update_agent(
    agent_type: str, body: AgentConfigUpdateRequest, state: AppStateDep, admin: User = _RequireAgentManagement
) -> dict:
    agent_type = agent_type.upper()
    if agent_type not in {t.value for t in AgentType}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown agent type")
    entry = agent_catalog.catalog_entry(agent_type)
    if not entry["administrable"]:
        detail = (
            "The Risk Governor has no admin-settable state here -- see docs/agent-governance.md §1."
            if agent_type == "RISK_GOVERNOR"
            else "This agent seat is not yet implemented."
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    if body.status is not None and body.status not in _ADMIN_SETTABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"status must be one of {sorted(_ADMIN_SETTABLE_STATUSES)}",
        )
    before = await state.repo.get_agent_config(agent_type)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    fields["updated_by"] = admin.user_id
    config = await state.repo.update_agent_config(agent_type, **fields)
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown agent type")
    if body.status is not None and before is not None and before["status"] != config["status"]:
        await record_audit_event(
            state,
            actor=admin,
            action="agent.status_change",
            resource_type="agent",
            resource_id=agent_type,
            before=before,
            after=config,
        )
    return _merge_agent_view(state, agent_type, config)


@router.post("/{agent_type}/run")
async def run_agent(agent_type: str, state: AppStateDep, _admin: User = _RequireAgentManagement) -> dict:
    """Manually triggers an agent's already-approved logic on demand (spec §39's "Run
    Manually"). Only `CHIEF_TRADING_AGENT` is independently triggerable today -- every
    other seat executes as an internal step of the Chief Trading Agent's or Chief
    Investment Agent's composed research cycle (see `docs/agent-governance.md` §2's
    org chart), so a per-sub-agent manual run is honestly reported as unavailable
    rather than faked."""
    agent_type = agent_type.upper()
    if agent_type != "CHIEF_TRADING_AGENT":
        entry = agent_catalog.catalog_entry(agent_type)
        if not entry["implemented"]:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown or unimplemented agent type")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This agent is not independently triggerable -- it executes as part of the Chief "
                "Trading Agent's or Chief Investment Agent's composed research cycle. Run "
                "CHIEF_TRADING_AGENT instead."
            ),
        )
    config = await state.repo.get_agent_config(agent_type)
    if config is not None and config["status"] in ("PAUSED", "DISABLED"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Chief Trading Agent is {config['status']}"
        )
    return await state.run_chief_trading_cycle()
