from __future__ import annotations

import logging

from config import get_settings
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from ..auth import User, authenticate, create_access_token, get_current_user
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
async def request_magic_link(body: MagicLinkRequest) -> dict:
    """Milestone-1 placeholder for the passwordless login flow described in
    docs/access-model.md. There is no `User` table yet (added in Milestone 2) and no
    `EmailProvider`/`MagicLinkToken` issuance yet (Milestone 3), so this endpoint
    intentionally does nothing except return the mandated generic response — it
    never reveals whether an email corresponds to a real account (there being none
    yet makes that trivially true, but the response contract is fixed now so the
    frontend and future real implementation never need to change it). No account,
    invitation, or token is created by this call, now or once wired for real.
    """
    logger.info("Magic-link login requested (not yet wired to real auth) for %s", body.email)
    return _GENERIC_MAGIC_LINK_RESPONSE


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
