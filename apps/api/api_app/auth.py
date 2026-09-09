"""Dev-mode auth: OAuth2/OIDC-compatible bearer JWT flow, local password grant.

`_DEV_USERS`/`POST /auth/login` is deliberately kept as the platform's fixed
break-glass/bootstrap credential set — not a general password-login feature for real
end users. Real accounts (`UserRow`) never authenticate with a password; they always
go through magic-link (`routers/auth.py`'s `/auth/magic-link/*`) or OIDC SSO. This
endpoint exists because something has to authenticate the very first administrator
before any `UserRow` exists to create more — see docs/access-model.md §1 "Bootstrap
credentials" for the full reasoning. RBAC role checks (`require_role`) do not change
based on which login path issued the session JWT.
"""

from __future__ import annotations
import os

import hashlib
from datetime import datetime, timedelta, timezone
from enum import Enum

import jwt
from config import get_settings
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from .deps import AppStateDep


class Role(str, Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    TRADER = "TRADER"
    RISK_MANAGER = "RISK_MANAGER"
    RESEARCHER = "RESEARCHER"
    VIEWER = "VIEWER"


class User(BaseModel):
    user_id: str
    email: str
    display_name: str
    roles: list[Role]
    # Only set for a magic-link-issued session (the JWT's `sid` claim) — a dev-mode or
    # OIDC token has no backing `Session` row and leaves this `None`. `POST /auth/logout`
    # uses it to revoke the session server-side; it is otherwise informational.
    session_id: str | None = None


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


# Dev-mode user directory. Real deployments replace this with an IdP-backed lookup.
_DEV_USERS: dict[str, dict] = {
    "trader@alphagasiq.local": {
        "user_id": "u-trader-1",
        "password_hash": _hash_password(os.environ.get("DEV_TRADER_PASSWORD", "trader-dev-password")),
        "display_name": "Demo Trader",
        "roles": [Role.TRADER, Role.RESEARCHER, Role.VIEWER],
    },
    "risk@alphagasiq.local": {
        "user_id": "u-risk-1",
        "password_hash": _hash_password(os.environ.get("DEV_RISK_PASSWORD", "risk-dev-password")),
        "display_name": "Demo Risk Manager",
        "roles": [Role.RISK_MANAGER, Role.VIEWER],
    },
    "superadmin@alphagasiq.local": {
        "user_id": "u-superadmin-1",
        "password_hash": _hash_password(os.environ.get("DEV_SUPERADMIN_PASSWORD", "superadmin-dev-password")),
        "display_name": "Demo Super Admin",
        "roles": [Role.SUPER_ADMIN, Role.ADMIN, Role.TRADER, Role.RISK_MANAGER, Role.RESEARCHER, Role.VIEWER],
    },
    "admin@alphagasiq.local": {
        "user_id": "u-admin-1",
        "password_hash": _hash_password(os.environ.get("DEV_ADMIN_PASSWORD", "admin-dev-password")),
        "display_name": "Demo Admin",
        "roles": [Role.ADMIN, Role.TRADER, Role.RISK_MANAGER, Role.RESEARCHER, Role.VIEWER],
    },
}

_security = HTTPBearer(auto_error=False)


def authenticate(email: str, password: str) -> User | None:
    record = _DEV_USERS.get(email)
    if not record or record["password_hash"] != _hash_password(password):
        return None
    return User(
        user_id=record["user_id"], email=email, display_name=record["display_name"], roles=record["roles"]
    )


def create_access_token(user: User, *, session_id: str | None = None, expires_at: datetime | None = None) -> str:
    """`session_id`/`expires_at` are set only by the magic-link verify flow
    (`routers/auth.py`) — they add a `sid` claim pointing at a real `Session` row, so
    that (and only that) session can be revoked server-side later (docs/access-model.md
    §4). Dev-mode and OIDC logins never pass these, so their tokens are byte-for-byte
    what they always were: a stateless JWT with no DB-backed revocation, unaffected by
    this milestone."""
    settings = get_settings()
    expire = expires_at or (datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes))
    payload = {
        "sub": user.user_id,
        "email": user.email,
        "name": user.display_name,
        "roles": [r.value for r in user.roles],
        "exp": expire,
    }
    if session_id is not None:
        payload["sid"] = session_id
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def decode_access_token(token: str, state: object | None = None) -> User:
    """`state` (an `AppState`, passed as `object` here to avoid an import cycle with
    `.state`) is only consulted when the token carries a `sid` claim — i.e. only for
    magic-link-issued sessions. A dev-mode/OIDC token decodes exactly as before, with
    no DB round trip at all."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc

    session_id = payload.get("sid")
    if session_id is not None:
        if state is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session store unavailable")
        session = await state.repo.get_session(session_id)  # type: ignore[attr-defined]
        if session is None or session["revoked_at"] is not None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has been revoked")
        expires_at = session["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session has expired")

    return User(
        user_id=payload["sub"],
        email=payload["email"],
        display_name=payload["name"],
        roles=[Role(r) for r in payload["roles"]],
        session_id=session_id,
    )


async def get_current_user(
    state: AppStateDep,
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return await decode_access_token(credentials.credentials, state)


_ANONYMOUS_USER = User(user_id="anonymous", email="anonymous@alphagasiq.local", display_name="Anonymous Viewer", roles=[Role.VIEWER])


async def get_optional_user(
    state: AppStateDep,
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> User:
    """Like `get_current_user` but falls back to a read-only anonymous viewer instead
    of raising 401. Used only for endpoints that are safe to explore without login
    (e.g. starting an AI Trader Chat session) — every write/approval endpoint still
    requires `get_current_user` / `require_role`."""
    if credentials is None:
        return _ANONYMOUS_USER
    try:
        return await decode_access_token(credentials.credentials, state)
    except HTTPException:
        return _ANONYMOUS_USER


# Interim bridge from the 8 DB-seeded roles (docs/access-model.md §5) to today's
# 5-value dev-mode `Role` enum every router still checks — used only until Milestone 4
# replaces `require_role` with real `require_permission(...)` checks against the
# seeded RBAC data. Mirrors the capability composition `_DEV_USERS` above already
# uses (e.g. the dev TRADER fixture also carries RESEARCHER+VIEWER) so a real
# magic-link-authenticated user gets route access equivalent to their dev-mode
# counterpart, rather than a single bare role that happens to gate nothing.
DB_ROLE_TO_DEV_ROLES: dict[str, list[Role]] = {
    "SUPER_ADMIN": [Role.ADMIN, Role.TRADER, Role.RISK_MANAGER, Role.RESEARCHER, Role.VIEWER],
    "ADMIN": [Role.ADMIN, Role.TRADER, Role.RISK_MANAGER, Role.RESEARCHER, Role.VIEWER],
    "TRADER": [Role.TRADER, Role.RESEARCHER, Role.VIEWER],
    "RISK_MANAGER": [Role.RISK_MANAGER, Role.VIEWER],
    "RESEARCHER": [Role.RESEARCHER, Role.VIEWER],
    "EXECUTIVE": [Role.VIEWER],
    "VIEWER": [Role.VIEWER],
    "API_USER": [Role.VIEWER],
}


def map_db_role_to_dev_roles(role_name: str) -> list[Role]:
    """Never raises: an unrecognized DB role name falls back to the safe minimum
    (`VIEWER`-only), the same "unrecognized claim -> VIEWER" posture `oidc.py`
    already uses for unmapped IdP role claims."""
    return DB_ROLE_TO_DEV_ROLES.get(role_name, [Role.VIEWER])


def require_role(*allowed: Role):
    async def _dependency(user: User = Depends(get_current_user)) -> User:
        if not any(r in user.roles for r in allowed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {[r.value for r in allowed]}",
            )
        return user

    return _dependency
