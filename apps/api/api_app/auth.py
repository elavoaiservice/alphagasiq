"""Dev-mode auth: OAuth2/OIDC-compatible bearer JWT flow, local password grant.

In production this is swapped for a real OIDC provider (Auth0/Cognito/Okta/etc.) behind
the same `/auth/login` contract; RBAC role checks (`require_role`) do not change.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from enum import Enum

import jwt
from config import get_settings
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel


class Role(str, Enum):
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


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


# Dev-mode user directory. Real deployments replace this with an IdP-backed lookup.
_DEV_USERS: dict[str, dict] = {
    "trader@alphagasiq.local": {
        "user_id": "u-trader-1",
        "password_hash": _hash_password("trader-dev-password"),
        "display_name": "Demo Trader",
        "roles": [Role.TRADER, Role.RESEARCHER, Role.VIEWER],
    },
    "risk@alphagasiq.local": {
        "user_id": "u-risk-1",
        "password_hash": _hash_password("risk-dev-password"),
        "display_name": "Demo Risk Manager",
        "roles": [Role.RISK_MANAGER, Role.VIEWER],
    },
    "admin@alphagasiq.local": {
        "user_id": "u-admin-1",
        "password_hash": _hash_password("admin-dev-password"),
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


def create_access_token(user: User) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {
        "sub": user.user_id,
        "email": user.email,
        "name": user.display_name,
        "roles": [r.value for r in user.roles],
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> User:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc
    return User(
        user_id=payload["sub"],
        email=payload["email"],
        display_name=payload["name"],
        roles=[Role(r) for r in payload["roles"]],
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return decode_access_token(credentials.credentials)


_ANONYMOUS_USER = User(user_id="anonymous", email="anonymous@alphagasiq.local", display_name="Anonymous Viewer", roles=[Role.VIEWER])


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_security),
) -> User:
    """Like `get_current_user` but falls back to a read-only anonymous viewer instead
    of raising 401. Used only for endpoints that are safe to explore without login
    (e.g. starting an AI Trader Chat session) — every write/approval endpoint still
    requires `get_current_user` / `require_role`."""
    if credentials is None:
        return _ANONYMOUS_USER
    try:
        return decode_access_token(credentials.credentials)
    except HTTPException:
        return _ANONYMOUS_USER


def require_role(*allowed: Role):
    async def _dependency(user: User = Depends(get_current_user)) -> User:
        if not any(r in user.roles for r in allowed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {[r.value for r in allowed]}",
            )
        return user

    return _dependency
