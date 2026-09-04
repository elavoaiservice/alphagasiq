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
memberships) can see it.

`AGENT` principal-type entitlements (gap-closure follow-up: `agent_is_entitled` below)
are evaluated independently of `dataset_is_entitled`'s USER/ROLE/WORKSPACE check, not
folded into the same allow-list trigger -- a dataset an admin restricted to one
specific human (a USER grant) should not silently also block the system's own
aggregate read path (`AppState._load_enterprise_positions`), since nobody granting
that USER entitlement was thinking about `ENTERPRISE_POSITION_READER_AGENT_TYPE` at
all. Only the presence of an `AGENT`-type grant on a dataset switches that dataset
into agent-allow-list mode."""

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


def agent_is_entitled(*, entitlements: list[EnterpriseDataEntitlement], agent_type: str) -> bool:
    """Whether a system agent identified by `agent_type` (e.g. `AppState.
    ENTERPRISE_POSITION_READER_AGENT_TYPE`) may read a dataset, given that dataset's
    entitlement rows. Mirrors `dataset_is_entitled`'s backward-compatible-default
    shape exactly, but scoped to `AGENT`-type grants only -- see this module's
    docstring for why a dataset's USER/ROLE/WORKSPACE grants don't affect this check.
    A dataset with zero `AGENT`-type grants is visible to every agent (today's
    unchanged default); once at least one exists, only a matching `agent_type` sees
    it."""
    agent_grants = [g for g in entitlements if g.principal_type == EnterpriseEntitlementPrincipalType.AGENT]
    if not agent_grants:
        return True
    return any(grant.principal_id == agent_type for grant in agent_grants)
