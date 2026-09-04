"""Milestone 8 (docs/alpha-intelligence.md section 11.1): `Workspace` -- a
grouping inside an `Organization` that enterprise data sources, datasets, and
entitlements can be scoped to. Every endpoint here is gated by
`admin.workspaces` (granted to ADMIN and SUPER_ADMIN)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from schemas import Workspace

from ..auth import User
from ..deps import AppStateDep
from ..entitlements import require_permission

router = APIRouter(prefix="/admin/workspaces", tags=["admin"])

_RequireWorkspaces = Depends(require_permission("admin.workspaces"))


class WorkspaceCreateRequest(BaseModel):
    organization_id: str
    name: str
    description: str = ""


@router.get("")
async def list_workspaces(
    state: AppStateDep, _admin: User = _RequireWorkspaces, organization_id: str | None = None
) -> list[dict]:
    return await state.repo.list_workspaces(organization_id=organization_id)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workspace(body: WorkspaceCreateRequest, state: AppStateDep, admin: User = _RequireWorkspaces) -> dict:
    if await state.repo.get_organization(body.organization_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown organization_id")
    workspace = Workspace(
        organization_id=body.organization_id, name=body.name, description=body.description, created_by=admin.user_id
    )
    await state.repo.save_workspace(workspace)
    return await state.repo.get_workspace(str(workspace.id))


@router.get("/{workspace_id}")
async def get_workspace(workspace_id: str, state: AppStateDep, _admin: User = _RequireWorkspaces) -> dict:
    workspace = await state.repo.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return workspace


class WorkspaceUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None


@router.patch("/{workspace_id}")
async def update_workspace(
    workspace_id: str, body: WorkspaceUpdateRequest, state: AppStateDep, _admin: User = _RequireWorkspaces
) -> dict:
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = await state.repo.update_workspace(workspace_id, **fields)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return updated


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(workspace_id: str, state: AppStateDep, _admin: User = _RequireWorkspaces) -> None:
    if not await state.repo.delete_workspace(workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")


class WorkspaceMemberRequest(BaseModel):
    user_id: str


@router.get("/{workspace_id}/members")
async def list_workspace_members(workspace_id: str, state: AppStateDep, _admin: User = _RequireWorkspaces) -> list[dict]:
    if await state.repo.get_workspace(workspace_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return await state.repo.list_workspace_members(workspace_id)


@router.post("/{workspace_id}/members", status_code=status.HTTP_201_CREATED)
async def add_workspace_member(
    workspace_id: str, body: WorkspaceMemberRequest, state: AppStateDep, admin: User = _RequireWorkspaces
) -> list[dict]:
    if await state.repo.get_workspace(workspace_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    await state.repo.add_workspace_member(workspace_id, body.user_id, added_by=admin.user_id)
    return await state.repo.list_workspace_members(workspace_id)


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_workspace_member(
    workspace_id: str, user_id: str, state: AppStateDep, _admin: User = _RequireWorkspaces
) -> None:
    if not await state.repo.remove_workspace_member(workspace_id, user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace member not found")
