"""RBAC permission resolution + feature-entitlement computation (docs/access-model.md
§§5-6, spec §§23-24). This is the Milestone 4 enforcement layer that sits on top of
the RBAC/feature data Milestone 2/3 already seed into the database.

Two identities can reach here:

- A magic-link user has a real `UserRow` with an actual `role_id` — permissions and
  features are resolved from *that* role directly. This matters because
  `auth.py::map_db_role_to_dev_roles` collapses `SUPER_ADMIN`/`EXECUTIVE`/`API_USER`
  down onto the 5-value dev-mode `Role` enum for route-level `require_role` checks
  elsewhere; resolving entitlements from `user.roles` instead of the real role would
  silently under-grant a `SUPER_ADMIN` (or over/under-grant `EXECUTIVE`/`API_USER`)
  down to whatever their bridged dev-mode roles happen to carry. Going back to the
  real `role_id` avoids that entirely.
- A dev-mode/OIDC user has no backing `UserRow` at all — for them, `user.roles`
  *is* the identity, and since every dev-mode `Role` enum value is string-identical
  to a real DB role name, permissions/features are resolved by unioning each of
  `user.roles`' DB-role grants directly.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status

from .auth import User, get_current_user
from .deps import AppStateDep


async def _resolve_user_record(user: User, state) -> dict | None:
    return await state.repo.get_user_by_id(user.user_id)


async def resolve_organization_id(user: User, state) -> str | None:
    """A magic-link user's `user_id` is a real `UserRow.id`; a dev-mode/OIDC user's
    is a synthetic string with no matching row. Either way this just returns `None`
    on a miss rather than raising — an unresolvable organization means no
    organization-scoped *feature override* applies to this caller (see
    `get_effective_features`), which is the correct, safe default there. It is
    deliberately NOT safe to reuse this same `None` for filtering *data visibility*
    (a `list_X(organization_id=None)` call skips organization filtering entirely on
    most repository methods) — use `resolve_organization_scope` for that instead."""
    record = await _resolve_user_record(user, state)
    return record["organization_id"] if record is not None else None


async def resolve_organization_scope(user: User, state) -> tuple[str | None, bool]:
    """Tenant-isolation retrofit (docs/alpha-intelligence.md section 11.1, Milestone
    9): returns `(organization_id, unrestricted)` for filtering *data visibility* —
    distinct from `resolve_organization_id` above, which is safe to return `None` on
    a miss only for feature-override lookups, never for deciding what data a caller
    can see. `unrestricted=True` only when the caller both has no resolvable
    organization *and* holds `admin.organizations` (a real cross-organization
    admin) — every other caller with no resolvable organization gets
    `unrestricted=False`, meaning callers must filter to platform-wide-only data
    (`organization_id IS NULL`) rather than silently returning every organization's
    scoped rows to someone `resolve_organization_id` simply couldn't identify."""
    organization_id = await resolve_organization_id(user, state)
    if organization_id is not None:
        return organization_id, False
    permissions = await get_effective_permissions(user, state)
    return None, "admin.organizations" in permissions


def record_is_visible(record_organization_id: str | None, caller_organization_id: str | None, unrestricted: bool) -> bool:
    """Whether a single already-fetched record (its own `organization_id`, `None`
    meaning platform-wide) is visible to a caller resolved via
    `resolve_organization_scope`. Used by every `get_{signal,impact,...}_by_id`
    endpoint (docs/alpha-intelligence.md section 11.1, Milestone 9) to close the gap
    those endpoints previously had: fetching a record by id performed no
    organization check at all, so any caller with the base view permission could
    read any organization's specific record regardless of their own."""
    if unrestricted:
        return True
    if record_organization_id is None:
        return True
    return record_organization_id == caller_organization_id


async def get_effective_permissions(user: User, state) -> set[str]:
    """The user's real DB role's permission grants if they have a `UserRow`;
    otherwise the union of every DB role's grants across `user.roles` (dev-mode/OIDC
    — see module docstring for why these two paths differ)."""
    record = await _resolve_user_record(user, state)
    if record is not None:
        role = await state.repo.get_role_by_id(record["role_id"])
        return await state.repo.get_permission_keys_for_role(role["name"]) if role is not None else set()

    permissions: set[str] = set()
    for role in user.roles:
        permissions |= await state.repo.get_permission_keys_for_role(role.value)
    return permissions


async def get_effective_features(user: User, state) -> dict[str, bool]:
    """Computes the effective (feature_key -> bool) map per docs/access-model.md §5:

        effective = globally_enabled AND role_grants AND org_grants AND NOT user_denied

    with one refinement for `security_sensitive` features: a user-level override can
    only *narrow* access there (an `enabled=True` override cannot grant a sensitive
    feature role/org don't already allow), whereas for a non-sensitive feature a
    user-level override can freely grant or deny regardless of role/org — this is
    spec §24's "deny-overrides for security-sensitive features".
    """
    features = await state.repo.list_features()
    record = await _resolve_user_record(user, state)

    role_keys: set[str] = set()
    if record is not None:
        role_keys = await state.repo.get_role_feature_keys(record["role_id"])
        organization_id = record["organization_id"]
    else:
        for role in user.roles:
            db_role = await state.repo.get_role_by_name(role.value)
            if db_role is not None:
                role_keys |= await state.repo.get_role_feature_keys(db_role["id"])
        organization_id = None

    org_overrides = await state.repo.get_organization_feature_overrides(organization_id) if organization_id else {}
    user_overrides = await state.repo.get_user_feature_overrides(user.user_id)

    effective: dict[str, bool] = {}
    for feature in features:
        key = feature["key"]
        global_ok = feature["globally_enabled"]
        role_ok = key in role_keys
        org_ok = org_overrides.get(key, True)
        base = global_ok and role_ok and org_ok

        override = user_overrides.get(key)
        if override is None:
            effective[key] = base
        elif feature["security_sensitive"]:
            effective[key] = base and override
        else:
            effective[key] = global_ok and override

    return effective


def require_permission(permission_key: str):
    """FastAPI dependency: 403s unless the authenticated user's effective permission
    set contains `permission_key`. Replaces `require_role(Role.ADMIN)` wherever a
    router wants the real, DB-backed check the access-model spec calls for."""

    async def _dependency(state: AppStateDep, user: User = Depends(get_current_user)) -> User:
        permissions = await get_effective_permissions(user, state)
        if permission_key not in permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires permission: {permission_key}"
            )
        return user

    return _dependency


def require_any_permission(*permission_keys: str):
    """Like `require_permission`, but satisfied by any one of several permissions —
    useful where a single endpoint covers several admin actions with different
    required permissions (e.g. an account-status-change endpoint whose required
    permission depends on the target status)."""

    async def _dependency(state: AppStateDep, user: User = Depends(get_current_user)) -> User:
        permissions = await get_effective_permissions(user, state)
        if not (permissions & set(permission_keys)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of permissions: {list(permission_keys)}",
            )
        return user

    return _dependency


async def ensure_permission(user: User, state, permission_key: str) -> None:
    """Non-dependency form of `require_permission`, for a permission check that has
    to happen partway through a handler (e.g. only after branching on request body
    contents) rather than up front in the route signature."""
    permissions = await get_effective_permissions(user, state)
    if permission_key not in permissions:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires permission: {permission_key}")


def require_feature(feature_key: str):
    """FastAPI dependency: 403s unless the authenticated user's effective feature
    entitlements grant `feature_key`. Not yet wired to any user-facing route — that's
    Milestone 5's job (dashboard/chat integration); exposed now so that milestone has
    a ready-made enforcement primitive to call."""

    async def _dependency(state: AppStateDep, user: User = Depends(get_current_user)) -> User:
        features = await get_effective_features(user, state)
        if not features.get(feature_key, False):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires feature: {feature_key}")
        return user

    return _dependency
