"""Tenant-isolation retrofit (docs/alpha-intelligence.md section 11.1,
Milestone 9): admin CRUD for `ModelRoutingPolicy` (governs whether a given
`EnterpriseDataClassification` may be sent to an external LLM provider for an
organization) and `RetentionPolicy` (how long that classification's data may
be kept), plus the endpoint that triggers a retention purge.
`organization_id=null` in a request body means a platform-default policy --
every admin editing that must hold `admin.organizations` in addition to the
policy-specific permission, since a platform default affects every
organization, not just the caller's own."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from schemas import EnterpriseDataClassification, ModelRoutingPolicy, RetentionPolicy

from ..auth import User
from ..deps import AppStateDep
from ..entitlements import ensure_permission, require_permission

router = APIRouter(prefix="/admin", tags=["admin"])

_RequireModelRouting = Depends(require_permission("admin.model_routing_policy"))
_RequireRetention = Depends(require_permission("admin.retention_policy"))


async def _ensure_platform_default_allowed(user: User, state, organization_id: str | None) -> None:
    if organization_id is None:
        await ensure_permission(user, state, "admin.organizations")


class ModelRoutingPolicyRequest(BaseModel):
    organization_id: str | None = None
    data_classification: EnterpriseDataClassification
    allow_external_llm_processing: bool
    allowed_provider: str | None = None
    allowed_region: str | None = None
    logging_allowed: bool = True


@router.get("/model-routing-policies")
async def list_model_routing_policies(
    state: AppStateDep, _admin: User = _RequireModelRouting, organization_id: str | None = None
) -> list[dict]:
    return await state.repo.list_model_routing_policies(organization_id=organization_id)


@router.post("/model-routing-policies", status_code=status.HTTP_201_CREATED)
async def create_model_routing_policy(
    body: ModelRoutingPolicyRequest, state: AppStateDep, admin: User = _RequireModelRouting
) -> dict:
    if body.organization_id is not None and await state.repo.get_organization(body.organization_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown organization_id")
    await _ensure_platform_default_allowed(admin, state, body.organization_id)
    policy = ModelRoutingPolicy(**body.model_dump(), created_by=admin.user_id)
    await state.repo.save_model_routing_policy(policy)
    return await state.repo.get_model_routing_policy(str(policy.id))


@router.delete("/model-routing-policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model_routing_policy(
    policy_id: str, state: AppStateDep, admin: User = _RequireModelRouting
) -> None:
    existing = await state.repo.get_model_routing_policy(policy_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model routing policy not found")
    await _ensure_platform_default_allowed(admin, state, existing["organization_id"])
    await state.repo.delete_model_routing_policy(policy_id)


class RetentionPolicyRequest(BaseModel):
    organization_id: str | None = None
    data_classification: EnterpriseDataClassification
    retention_days: int | None = None


@router.get("/retention-policies")
async def list_retention_policies(
    state: AppStateDep, _admin: User = _RequireRetention, organization_id: str | None = None
) -> list[dict]:
    return await state.repo.list_retention_policies(organization_id=organization_id)


@router.post("/retention-policies", status_code=status.HTTP_201_CREATED)
async def create_retention_policy(
    body: RetentionPolicyRequest, state: AppStateDep, admin: User = _RequireRetention
) -> dict:
    if body.organization_id is not None and await state.repo.get_organization(body.organization_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown organization_id")
    await _ensure_platform_default_allowed(admin, state, body.organization_id)
    policy = RetentionPolicy(**body.model_dump(), created_by=admin.user_id)
    await state.repo.save_retention_policy(policy)
    return await state.repo.get_retention_policy(str(policy.id))


@router.delete("/retention-policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_retention_policy(policy_id: str, state: AppStateDep, admin: User = _RequireRetention) -> None:
    existing = await state.repo.get_retention_policy(policy_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Retention policy not found")
    await _ensure_platform_default_allowed(admin, state, existing["organization_id"])
    await state.repo.delete_retention_policy(policy_id)


class ApplyRetentionRequest(BaseModel):
    organization_id: str | None = None
    data_classification: EnterpriseDataClassification


@router.post("/retention-policies/apply")
async def apply_retention_policy(
    body: ApplyRetentionRequest, state: AppStateDep, admin: User = _RequireRetention
) -> dict:
    """Purges every `EnterpriseRecordRow` older than the resolved retention
    cutoff for `(organization_id, data_classification)`. A no-op (zero rows
    purged) when no policy is configured for that pair -- see
    `AppState.apply_retention_policy`'s docstring."""
    await _ensure_platform_default_allowed(admin, state, body.organization_id)
    return await state.apply_retention_policy(
        organization_id=body.organization_id, data_classification=body.data_classification
    )
