"""Milestone 10: model management (spec §43, `docs/agent-governance.md` §6).

**An agent may never be configured to use a model that isn't `APPROVED`.** This is
enforced structurally in `SqlAppRepository.transition_agent_version_status` (Milestone
9), which rejects moving an `AgentVersion` referencing a non-`APPROVED` model to
`APPROVED`/`PRODUCTION` -- not left to admin-UI convention. Every status change here is
recorded as an audit event (`apps/api/api_app/audit.py`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..audit import record_audit_event
from ..auth import User
from ..deps import AppStateDep
from ..entitlements import require_permission

router = APIRouter(prefix="/admin/models", tags=["admin"])

_RequireModelManagement = Depends(require_permission("admin.model_management"))

_MODEL_STATUSES = {"AVAILABLE", "TESTING", "APPROVED", "DEPRECATED", "DISABLED"}


class ModelDefinitionCreateRequest(BaseModel):
    provider: str
    model_name: str
    version: str | None = None
    purpose: str | None = None
    context_window: int | None = None
    cost_per_1k_input_tokens: float | None = None
    cost_per_1k_output_tokens: float | None = None
    notes: str | None = None


@router.get("")
async def list_models(state: AppStateDep, _admin: User = _RequireModelManagement) -> list[dict]:
    return await state.repo.list_model_definitions()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_model(
    body: ModelDefinitionCreateRequest, state: AppStateDep, admin: User = _RequireModelManagement
) -> dict:
    created = await state.repo.create_model_definition(**body.model_dump())
    await record_audit_event(
        state,
        actor=admin,
        action="model.create",
        resource_type="model_definition",
        resource_id=created["id"],
        after=created,
    )
    return created


@router.get("/{model_id}")
async def get_model(model_id: str, state: AppStateDep, _admin: User = _RequireModelManagement) -> dict:
    model = await state.repo.get_model_definition(model_id)
    if model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown model definition")
    return model


class ModelStatusUpdateRequest(BaseModel):
    status: str
    reason: str | None = None


@router.patch("/{model_id}/status")
async def update_model_status(
    model_id: str, body: ModelStatusUpdateRequest, state: AppStateDep, admin: User = _RequireModelManagement
) -> dict:
    if body.status not in _MODEL_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"status must be one of {sorted(_MODEL_STATUSES)}"
        )
    before = await state.repo.get_model_definition(model_id)
    if before is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown model definition")
    after = await state.repo.update_model_definition_status(model_id, body.status, actor=admin.user_id)
    await record_audit_event(
        state,
        actor=admin,
        action="model.status_change",
        resource_type="model_definition",
        resource_id=model_id,
        before=before,
        after=after,
        reason=body.reason,
    )
    return after
