"""Magic-link issuance (docs/access-model.md §3, spec §19). Shared by
`routers/auth.py` (login requests, verification) and `routers/admin_users.py`
(initial invitation at account creation, admin-initiated resend) so both call sites
go through the exact same token-generation/hashing/expiry/email-dispatch path.

Token requirements from spec §19, all satisfied here: cryptographically random
(`secrets.token_urlsafe`), single-use (`consumed_at`, checked by the verify endpoint),
hashed at rest (only `hash_token()`'s sha256 digest is ever persisted — the raw token
exists only in the returned email URL and is never logged or stored), short expiration
(`magic_link_expire_minutes`, default 15).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from config import get_settings

from . import email_service


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _magic_link_url(raw_token: str) -> str:
    settings = get_settings()
    return f"{settings.api_base_url}/api/v1/auth/magic-link/verify?token={raw_token}"


async def _issue_token(state, *, user_id: str, purpose: str, requested_ip: str | None, user_agent: str | None) -> str:
    settings = get_settings()
    raw_token = secrets.token_urlsafe(32)
    await state.repo.create_magic_link_token(
        user_id=user_id,
        token_hash=hash_token(raw_token),
        purpose=purpose,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.magic_link_expire_minutes),
        requested_ip=requested_ip,
        user_agent=user_agent,
    )
    return raw_token


async def issue_and_send_login_link(
    state, *, user: dict, requested_ip: str | None = None, user_agent: str | None = None
) -> None:
    """An `ACTIVE` user requesting a fresh login link from `/login`."""
    settings = get_settings()
    await state.repo.revoke_unconsumed_magic_link_tokens_for_user(user["id"], purpose="LOGIN")
    raw_token = await _issue_token(state, user_id=user["id"], purpose="LOGIN", requested_ip=requested_ip, user_agent=user_agent)
    message = email_service.build_magic_link_login_email(
        email=user["email"], magic_link_url=_magic_link_url(raw_token), expires_minutes=settings.magic_link_expire_minutes
    )
    await state.email_provider.send(message)


async def issue_and_send_initial_invitation(state, *, user: dict) -> None:
    """Called exactly once, immediately after `POST /admin/users` creates the row
    (spec §16 "Account Creation Email")."""
    settings = get_settings()
    role = await state.repo.get_role_by_id(user["role_id"])
    raw_token = await _issue_token(state, user_id=user["id"], purpose="INITIAL_INVITATION", requested_ip=None, user_agent=None)
    message = email_service.build_account_created_email(
        first_name=user["first_name"],
        last_name=user["last_name"],
        email=user["email"],
        role_name=role["name"] if role is not None else "—",
        magic_link_url=_magic_link_url(raw_token),
        expires_minutes=settings.magic_link_expire_minutes,
    )
    await state.email_provider.send(message)


async def issue_and_send_resend_invitation(
    state, *, user: dict, requested_ip: str | None = None, user_agent: str | None = None
) -> None:
    """Spec §18 "Resend Invitation": generate a new link, invalidate every prior
    unused invitation link, send it, and (the caller's responsibility) record an
    audit event. Used both by an admin's explicit "Resend Invitation" action and by a
    still-`INVITED` user requesting another link from `/login` — spec §21's "Request
    another invitation if an INVITED account is eligible"."""
    settings = get_settings()
    await state.repo.revoke_unconsumed_magic_link_tokens_for_user(user["id"], purpose="INITIAL_INVITATION")
    raw_token = await _issue_token(
        state, user_id=user["id"], purpose="INITIAL_INVITATION", requested_ip=requested_ip, user_agent=user_agent
    )
    message = email_service.build_invitation_resent_email(
        first_name=user["first_name"],
        last_name=user["last_name"],
        email=user["email"],
        magic_link_url=_magic_link_url(raw_token),
        expires_minutes=settings.magic_link_expire_minutes,
    )
    await state.email_provider.send(message)
