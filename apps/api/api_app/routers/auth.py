from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from config import get_settings
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from .. import magic_link
from ..account_states import AUTHENTICATABLE_STATUSES, AccountStatus
from ..auth import User, authenticate, create_access_token, get_current_user, map_db_role_to_dev_roles
from ..deps import AppStateDep
from ..oidc import OidcNotConfigured, build_authorization_redirect_url, handle_callback, oidc_configured

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: User


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest) -> LoginResponse:
    user = authenticate(body.email, body.password)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token(user)
    return LoginResponse(access_token=token, user=user)


@router.get("/me", response_model=User)
async def me(user: User = Depends(get_current_user)) -> User:
    return user


class MagicLinkRequest(BaseModel):
    email: str


_GENERIC_MAGIC_LINK_RESPONSE = {
    "detail": "If an authorized AlphaGasIQ account exists for this email, a secure sign-in link has been sent."
}


@router.post("/magic-link/request")
async def request_magic_link(body: MagicLinkRequest, request: Request, state: AppStateDep) -> dict:
    """Always returns the same generic response regardless of whether the email
    matches an account, whether that account is eligible, or whether the request was
    rate-limited — this is the non-enumerating contract fixed since Milestone 1
    (docs/access-model.md §3). Everything below this point only decides whether an
    email actually goes out; it never changes what the caller sees.
    """
    email = body.email.strip().lower()
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    # Rate limit by email and by IP independently — either budget being exhausted
    # silently no-ops the rest of this handler (spec §19 "Rate limiting").
    email_ok = state.magic_link_rate_limiter.allow(f"email:{email}")
    ip_ok = state.magic_link_rate_limiter.allow(f"ip:{client_ip}") if client_ip else True
    if not (email_ok and ip_ok):
        logger.info("Magic-link request rate-limited for %s", email)
        return _GENERIC_MAGIC_LINK_RESPONSE

    user = await state.repo.get_user_by_email(email)
    if user is None or AccountStatus(user["status"]) not in AUTHENTICATABLE_STATUSES:
        logger.info("Magic-link requested for unknown/ineligible email (no-op, generic response returned)")
        return _GENERIC_MAGIC_LINK_RESPONSE

    if user["status"] == AccountStatus.INVITED.value:
        await magic_link.issue_and_send_resend_invitation(state, user=user, requested_ip=client_ip, user_agent=user_agent)
    else:
        await magic_link.issue_and_send_login_link(state, user=user, requested_ip=client_ip, user_agent=user_agent)
    return _GENERIC_MAGIC_LINK_RESPONSE


@router.get("/magic-link/verify")
async def verify_magic_link(token: str, state: AppStateDep) -> RedirectResponse:
    """The link a user clicks from their email. Unlike `/magic-link/request`, this
    endpoint's failure modes are allowed to be specific (401 with a reason) — there is
    no email-enumeration concern here, since reaching this endpoint already requires
    possessing a token that was only ever sent to one address."""
    token_hash = magic_link.hash_token(token)
    record = await state.repo.get_magic_link_token_by_hash(token_hash)
    if record is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid sign-in link")
    if record["consumed_at"] is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="This sign-in link has already been used")
    if record["revoked_at"] is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="This sign-in link is no longer valid")

    expires_at = record["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="This sign-in link has expired")

    user = await state.repo.get_user_by_id(record["user_id"])
    if user is None or AccountStatus(user["status"]) not in AUTHENTICATABLE_STATUSES:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="This account is not eligible to sign in")

    # Consume before creating the session: even if something below fails, this exact
    # token can never be replayed (spec §19 "Immediate invalidation after use").
    await state.repo.consume_magic_link_token(record["id"])

    if user["status"] == AccountStatus.INVITED.value:
        user = await state.repo.mark_user_activated(user["id"])
    else:
        await state.repo.record_user_login(user["id"])

    settings = get_settings()
    session_expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.magic_link_session_minutes)
    session_row = await state.repo.create_session(user_id=user["id"], expires_at=session_expires_at)

    role = await state.repo.get_role_by_id(user["role_id"])
    dev_roles = map_db_role_to_dev_roles(role["name"] if role is not None else "VIEWER")
    session_user = User(
        user_id=user["id"],
        email=user["email"],
        display_name=f"{user['first_name']} {user['last_name']}",
        roles=dev_roles,
    )
    session_token = create_access_token(session_user, session_id=session_row["id"], expires_at=session_expires_at)

    frontend_origin = settings.cors_origins.split(",")[0].strip()
    return RedirectResponse(f"{frontend_origin}/platform#access_token={session_token}")


@router.post("/logout")
async def logout(state: AppStateDep, user: User = Depends(get_current_user)) -> dict:
    """Revokes the backing `Session` row for a magic-link session (so the same JWT is
    rejected by every subsequent request, per docs/access-model.md §4 "session
    revocation"). A dev-mode/OIDC token has no `Session` row (`user.session_id` is
    `None`) — there is nothing server-side to revoke, so logout for those is already
    complete the moment the client discards the token, exactly as before this
    milestone."""
    if user.session_id is not None:
        await state.repo.revoke_session(user.session_id)
    return {"detail": "Logged out"}


@router.get("/sessions")
async def list_my_sessions(state: AppStateDep, user: User = Depends(get_current_user)) -> list[dict]:
    """Spec §20 "Device/session history" — a user's own view of their active/past
    sessions. Only meaningful for magic-link-authenticated users (dev-mode/OIDC
    sessions aren't tracked in the `sessions` table)."""
    return await state.repo.list_sessions_for_user(user.user_id)


@router.get("/mode")
async def auth_mode() -> dict:
    """Tells the frontend whether real SSO is available so it can show an "OIDC
    login" option alongside (never instead of) the dev-mode identity picker."""
    return {"oidc_configured": oidc_configured()}


@router.get("/oidc/login")
async def oidc_login() -> RedirectResponse:
    try:
        url = await build_authorization_redirect_url()
    except OidcNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    return RedirectResponse(url)


@router.get("/oidc/callback")
async def oidc_callback(code: str, state: str) -> RedirectResponse:
    try:
        user = await handle_callback(code=code, state=state)
    except OidcNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc)) from exc
    token = create_access_token(user)
    settings = get_settings()
    frontend_origin = settings.cors_origins.split(",")[0].strip()
    # Fragment (not query string) so the session token never lands in server access
    # logs or gets sent as a Referer header; the frontend picks it up client-side.
    return RedirectResponse(f"{frontend_origin}/platform#access_token={token}")
