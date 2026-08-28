"""Fine-grained per-dataset `EnterpriseDataEntitlement` enforcement (docs/alpha-
intelligence.md section 11.2, Milestone 10 follow-up).

Every enterprise read path built through Milestone 10 scoped visibility by
organization only -- a caller saw every dataset their organization registered, not
only ones they were specifically entitled to, even though `EnterpriseDataEntitlement`
(USER/ROLE/WORKSPACE/AGENT principal types, admin CRUD already at
`POST/GET/DELETE /admin/enterprise/datasets/{id}/entitlements`) existed and could be
granted. This module is the real enforcement primitive that was missing: a pure
function, zero I/O, deciding whether one principal (a user, identified by id, roles,
and workspace memberships) may see one dataset given that dataset's entitlement rows.

**Backward-compatible default**: a dataset with zero entitlement rows is visible to
every member of its owning organization, exactly the pre-Milestone-10-follow-up
behavior -- entitlements are an opt-in narrowing, not a default-deny gate flipped on
for every dataset the instant this shipped. Once at least one entitlement row exists
for a dataset, it switches to allow-list mode: only a principal matching one of that
dataset's grants (their own `user_id`, one of their roles, or one of their workspace
memberships) can see it. `AGENT` principal-type entitlements are for a future
agent-classification integration (see `model_routing.py`'s module docstring for the
analogous, still-open agent-side gap) and are not evaluated against a human caller
here."""

from __future__ import annotations

from schemas import EnterpriseDataEntitlement, EnterpriseEntitlementPrincipalType


def dataset_is_entitled(
    *,
    entitlements: list[EnterpriseDataEntitlement],
    user_id: str,
    roles: list[str],
    workspace_ids: list[str],
) -> bool:
    if not entitlements:
        return True
    role_set = set(roles)
    workspace_set = set(workspace_ids)
    for grant in entitlements:
        if grant.principal_type == EnterpriseEntitlementPrincipalType.USER and grant.principal_id == user_id:
            return True
        if grant.principal_type == EnterpriseEntitlementPrincipalType.ROLE and grant.principal_id in role_set:
            return True
        if (
            grant.principal_type == EnterpriseEntitlementPrincipalType.WORKSPACE
            and grant.principal_id in workspace_set
        ):
            return True
    return False
