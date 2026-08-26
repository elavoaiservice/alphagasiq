from __future__ import annotations

from fastapi import APIRouter, Depends
from schemas import AgentType

from ..agent_catalog import AGENT_TEAM, IMPLEMENTED_AGENT_TYPES
from ..auth import Role, User, require_role
from ..deps import AppStateDep

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("")
async def org_chart(state: AppStateDep):
    last_by_type: dict[str, str] = {}
    for result in state.agent_execution_log:
        last_by_type[result.agent_type.value] = result.status.value

    return [
        {
            "agent_type": t.value,
            "team": AGENT_TEAM.get(t.value, "UNASSIGNED"),
            "implemented": t.value in IMPLEMENTED_AGENT_TYPES,
            "last_status": last_by_type.get(
                t.value, "NEVER_RUN" if t.value in IMPLEMENTED_AGENT_TYPES else "NOT_BUILT"
            ),
        }
        for t in AgentType
    ]


@router.get("/{agent_type}/executions")
async def executions(agent_type: str, state: AppStateDep, limit: int = 20):
    matches = [r for r in state.agent_execution_log if r.agent_type.value == agent_type.upper()]
    return matches[-limit:]


@router.post("/chief-trading/run")
async def run_chief_trading(
    state: AppStateDep,
    user: User = Depends(require_role(Role.RESEARCHER, Role.TRADER, Role.ADMIN)),
):
    return await state.run_chief_trading_cycle()
