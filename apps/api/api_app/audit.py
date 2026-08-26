"""Thin helper over `SqlAppRepository.record_audit_event` (spec §55,
`docs/agent-governance.md` §7) so every call site records the same shape
consistently. The underlying table is append-only -- there is no corresponding
update/delete helper here or in the repository, ever.
"""

from __future__ import annotations

from typing import Any

from fastapi.encoders import jsonable_encoder

from .auth import User


async def record_audit_event(
    state: Any,
    *,
    actor: User | None,
    action: str,
    resource_type: str,
    resource_id: str,
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
) -> dict:
    """`before`/`after` snapshots often carry `datetime`s straight from a repository
    dict (e.g. `updated_at`) -- `jsonable_encoder` converts them (and anything else
    non-JSON-native) to plain JSON-safe values before they reach the `JSON` column."""
    return await state.repo.record_audit_event(
        actor_user_id=actor.user_id if actor is not None else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        before=jsonable_encoder(before) if before is not None else None,
        after=jsonable_encoder(after) if after is not None else None,
        reason=reason,
    )
