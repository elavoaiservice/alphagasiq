"""Admin-only user/organization provisioning — the only place a `User` row can ever
be created (docs/access-model.md "No Self-Registration"). Gated by `require_role`
today; a DB-backed `admin.users.create`-style permission check replaces this once
Milestone 4 wires real RBAC enforcement (the seeded `RolePermission` data this
endpoint's `POST /admin/users` inserts into is already correct for that cutover).
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from .. import magic_link
from ..account_states import AccountStatus, InvalidAccountStateTransition, validate_transition
from ..auth import Role, User, require_role
from ..deps import AppStateDep
from ..email_service import build_account_status_changed_email

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# Every admin endpoint in this router requires the dev-mode ADMIN role today. See the
# module docstring for why this isn't yet `require_permission("admin.users.create")`.
_RequireAdmin = Depends(require_role(Role.ADMIN))


class OrganizationCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    website: str | None = Field(default=None, max_length=300)
    industry: str | None = Field(default=None, max_length=150)
    company_type: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    state_region: str | None = Field(default=None, max_length=100)
    billing_plan: str | None = Field(default=None, max_length=100)
    account_owner: str | None = Field(default=None, max_length=200)
    primary_contact: str | None = Field(default=None, max_length=200)
    feature_package: str | None = Field(default=None, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)


class OrganizationOut(BaseModel):
    id: str
    name: str
    website: str | None
    industry: str | None
    company_type: str | None
    country: str | None
    state_region: str | None
    status: str
    billing_plan: str | None
    account_owner: str | None
    primary_contact: str | None
    feature_package: str | None
    data_entitlements: dict
    notes: str | None
    created_at: datetime
    updated_at: datetime


class RoleOut(BaseModel):
    id: str
    name: str
    description: str | None


class UserCreateRequest(BaseModel):
    """Fields required per docs/access-model.md §10 (spec §10). `company_name` drives
    the organization lookup-or-create-inline behavior from spec §14 — if an
    organization with this exact name already exists the user is attached to it,
    otherwise a new one is created from `company_name`/`company_website`/
    `company_type`/`country`/`state_region`."""

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    business_email: EmailStr
    company_name: str = Field(min_length=1, max_length=200)
    company_website: str | None = Field(default=None, max_length=300)
    company_type: str | None = Field(default=None, max_length=100)
    job_title: str | None = Field(default=None, max_length=150)
    department: str | None = Field(default=None, max_length=150)
    phone: str | None = Field(default=None, max_length=50)
    country: str | None = Field(default=None, max_length=100)
    state_region: str | None = Field(default=None, max_length=100)
    primary_use_case: str | None = Field(default=None, max_length=100)
    market_experience: str | None = Field(default=None, max_length=100)
    role: str = Field(description="One of the seeded Role names, e.g. TRADER, RESEARCHER, ADMIN")
    expiration_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=2000)


class UserOut(BaseModel):
    id: str
    first_name: str
    last_name: str
    email: str
    organization_id: str
    organization_name: str | None = None
    job_title: str | None
    department: str | None
    phone: str | None
    country: str | None
    state_region: str | None
    primary_use_case: str | None
    market_experience: str | None
    role_id: str
    role_name: str | None = None
    status: str
    expiration_at: datetime | None
    created_by: str | None
    created_at: datetime
    updated_at: datetime
    activated_at: datetime | None
    last_login_at: datetime | None


class AccountStatusChangeRequest(BaseModel):
    status: AccountStatus


def _to_user_out(user: dict, *, organization_name: str | None, role_name: str | None) -> UserOut:
    return UserOut(**user, organization_name=organization_name, role_name=role_name)


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(state: AppStateDep, _admin: User = _RequireAdmin) -> list[dict]:
    return await state.repo.list_roles()


@router.post("/organizations", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
async def create_organization(
    body: OrganizationCreateRequest, state: AppStateDep, _admin: User = _RequireAdmin
) -> dict:
    if await state.repo.find_organization_by_name(body.name) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An organization with this name already exists")
    return await state.repo.create_organization(
        name=body.name,
        website=body.website,
        industry=body.industry,
        company_type=body.company_type,
        country=body.country,
        state_region=body.state_region,
        billing_plan=body.billing_plan,
        account_owner=body.account_owner,
        primary_contact=body.primary_contact,
        feature_package=body.feature_package,
        notes=body.notes,
    )


@router.get("/organizations", response_model=list[OrganizationOut])
async def list_organizations(state: AppStateDep, _admin: User = _RequireAdmin) -> list[dict]:
    return await state.repo.list_organizations()


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(body: UserCreateRequest, state: AppStateDep, admin: User = _RequireAdmin) -> UserOut:
    email = str(body.business_email).lower()
    if await state.repo.get_user_by_email(email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists")

    role = await state.repo.get_role_by_name(body.role)
    if role is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown role: {body.role}")

    organization = await state.repo.find_organization_by_name(body.company_name)
    if organization is None:
        organization = await state.repo.create_organization(
            name=body.company_name,
            website=body.company_website,
            company_type=body.company_type,
            country=body.country,
            state_region=body.state_region,
        )

    # Every new account starts INVITED regardless of what's requested — per spec §15's
    # explicit workflow ("Create Account -> User Status = INVITED"), the only way to
    # reach ACTIVE is completing the magic-link invitation (Milestone 3). Any other
    # status change happens post-creation via POST /admin/users/{id}/status.
    user = await state.repo.create_user(
        first_name=body.first_name,
        last_name=body.last_name,
        email=email,
        organization_id=organization["id"],
        job_title=body.job_title,
        department=body.department,
        phone=body.phone,
        country=body.country,
        state_region=body.state_region,
        primary_use_case=body.primary_use_case,
        market_experience=body.market_experience,
        role_id=role["id"],
        status=AccountStatus.INVITED.value,
        expiration_at=body.expiration_at,
        created_by=admin.user_id,
    )
    await magic_link.issue_and_send_initial_invitation(state, user=user)
    return _to_user_out(user, organization_name=organization["name"], role_name=role["name"])


@router.post("/users/{user_id}/resend-invitation", response_model=UserOut)
async def resend_invitation(user_id: str, state: AppStateDep, _admin: User = _RequireAdmin) -> UserOut:
    """Spec §18 "Resend Invitation" — only valid for a still-`INVITED` account.
    Generates a fresh Magic Link, invalidates every prior unused invitation link, and
    sends the new invitation email (`magic_link.issue_and_send_resend_invitation`
    handles all three)."""
    user = await state.repo.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user["status"] != AccountStatus.INVITED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitation can only be resent for a user in INVITED status",
        )
    await magic_link.issue_and_send_resend_invitation(state, user=user)
    organization = await state.repo.get_organization(user["organization_id"])
    role = await state.repo.get_role_by_id(user["role_id"])
    return _to_user_out(
        user,
        organization_name=organization["name"] if organization else None,
        role_name=role["name"] if role else None,
    )


@router.get("/users", response_model=list[UserOut])
async def list_users(state: AppStateDep, _admin: User = _RequireAdmin) -> list[UserOut]:
    users = await state.repo.list_users()
    organizations = {o["id"]: o["name"] for o in await state.repo.list_organizations()}
    roles = {r["id"]: r["name"] for r in await state.repo.list_roles()}
    return [
        _to_user_out(
            u, organization_name=organizations.get(u["organization_id"]), role_name=roles.get(u["role_id"])
        )
        for u in users
    ]


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(user_id: str, state: AppStateDep, _admin: User = _RequireAdmin) -> UserOut:
    user = await state.repo.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    organization = await state.repo.get_organization(user["organization_id"])
    role = await state.repo.get_role_by_id(user["role_id"])
    return _to_user_out(
        user,
        organization_name=organization["name"] if organization else None,
        role_name=role["name"] if role else None,
    )


@router.post("/users/{user_id}/status", response_model=UserOut)
async def change_user_status(
    user_id: str, body: AccountStatusChangeRequest, state: AppStateDep, _admin: User = _RequireAdmin
) -> UserOut:
    user = await state.repo.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    current_status = AccountStatus(user["status"])
    try:
        validate_transition(current_status, body.status)
    except InvalidAccountStateTransition as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    updated = await state.repo.update_user_status(user_id, body.status.value)

    if body.status in (AccountStatus.SUSPENDED, AccountStatus.ACTIVE, AccountStatus.DISABLED, AccountStatus.REVOKED):
        message = build_account_status_changed_email(
            first_name=updated["first_name"], email=updated["email"], new_status=body.status.value
        )
        await state.email_provider.send(message)

    organization = await state.repo.get_organization(updated["organization_id"])
    role = await state.repo.get_role_by_id(updated["role_id"])
    return _to_user_out(
        updated,
        organization_name=organization["name"] if organization else None,
        role_name=role["name"] if role else None,
    )


@router.get("/users/{user_id}/sessions")
async def list_user_sessions(user_id: str, state: AppStateDep, _admin: User = _RequireAdmin) -> list[dict]:
    """Spec §20: "Allow administrators to view active sessions without exposing
    session secrets" — a `Session` row carries no secret (the JWT itself is never
    stored), so this listing is already safe to return as-is."""
    if await state.repo.get_user_by_id(user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return await state.repo.list_sessions_for_user(user_id)


@router.post("/users/{user_id}/sessions/{session_id}/revoke")
async def revoke_user_session(user_id: str, session_id: str, state: AppStateDep, _admin: User = _RequireAdmin) -> dict:
    """Spec §20 "Admin-initiated session revocation"."""
    session = await state.repo.get_session(session_id)
    if session is None or session["user_id"] != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    revoked = await state.repo.revoke_session(session_id)
    return revoked
