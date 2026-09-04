"""Real OIDC (Authorization Code + PKCE) login, additive behind the dev-mode
password-grant login in `auth.py`.

Only active when `Settings.oidc_issuer_url` (+ client id/secret/redirect_uri) is
configured; every environment that leaves it unset — every local/dev/docker-compose
default — falls through to the existing dev login untouched, reporting
`oidc_configured: False` via `GET /auth/mode` rather than erroring. Same honest
not-configured pattern the rest of this codebase uses for EIA/NOAA/CME (see
`docs/data-sources.md`).

Once the IdP redirects back with an authorization code, this module validates the ID
token's signature against the IdP's live JWKS (`PyJWKClient`, cached per issuer) and
checks issuer/audience/nonce, then maps ID token claims onto this platform's own
`User`/`Role` — the resulting session is a normal `create_access_token()` JWT, so every
downstream `get_current_user`/`require_role` dependency and every router is completely
unaware whether a session came from dev login or real SSO.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import httpx
import jwt
from config import get_settings
from fastapi import HTTPException, status

from .auth import Role, User

_STATE_TOKEN_TYPE = "oidc_state"
_STATE_TOKEN_TTL_SECONDS = 600

# Per-issuer caches: OIDC discovery documents and JWKS clients change rarely and are
# safe (and expected, per the OIDC spec) to reuse for the life of the process.
_discovery_cache: dict[str, dict] = {}
_jwks_client_cache: dict[str, jwt.PyJWKClient] = {}


class OidcNotConfigured(Exception):
    """Raised when an /auth/oidc/* endpoint is hit but no OIDC provider is configured."""


def oidc_configured() -> bool:
    s = get_settings()
    return bool(s.oidc_issuer_url and s.oidc_client_id and s.oidc_client_secret and s.oidc_redirect_uri)


def _require_configured() -> None:
    if not oidc_configured():
        raise OidcNotConfigured(
            "OIDC is not configured on this deployment — set OIDC_ISSUER_URL, OIDC_CLIENT_ID, "
            "OIDC_CLIENT_SECRET, and OIDC_REDIRECT_URI to enable real SSO login."
        )


async def _discover(issuer_url: str) -> dict:
    if issuer_url in _discovery_cache:
        return _discovery_cache[issuer_url]
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(issuer_url.rstrip("/") + "/.well-known/openid-configuration")
        resp.raise_for_status()
        doc = resp.json()
    _discovery_cache[issuer_url] = doc
    return doc


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _generate_pkce_pair() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _encode_state(*, code_verifier: str, nonce: str) -> str:
    """Carries the PKCE verifier + nonce across the redirect to the IdP and back as a
    signed, short-lived JWT passed through the standard OIDC `state` parameter —
    avoids needing server-side session storage for a request that spans two separate
    HTTP requests to this stateless API."""
    settings = get_settings()
    payload = {
        "typ": _STATE_TOKEN_TYPE,
        "code_verifier": code_verifier,
        "nonce": nonce,
        "exp": datetime.now(timezone.utc) + timedelta(seconds=_STATE_TOKEN_TTL_SECONDS),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _decode_state(state: str) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(state, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired OIDC state") from exc
    if payload.get("typ") != _STATE_TOKEN_TYPE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OIDC state token")
    return payload


async def build_authorization_redirect_url() -> str:
    _require_configured()
    settings = get_settings()
    discovery = await _discover(settings.oidc_issuer_url)
    code_verifier, code_challenge = _generate_pkce_pair()
    nonce = _b64url(secrets.token_bytes(16))
    state = _encode_state(code_verifier=code_verifier, nonce=nonce)

    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": settings.oidc_redirect_uri,
        "scope": "openid profile email",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if settings.oidc_audience:
        params["audience"] = settings.oidc_audience
    query = str(httpx.QueryParams(params))
    return f"{discovery['authorization_endpoint']}?{query}"


def _get_jwks_client(jwks_uri: str) -> jwt.PyJWKClient:
    if jwks_uri not in _jwks_client_cache:
        _jwks_client_cache[jwks_uri] = jwt.PyJWKClient(jwks_uri)
    return _jwks_client_cache[jwks_uri]


def _validate_id_token(id_token: str, *, discovery: dict, expected_nonce: str) -> dict:
    settings = get_settings()
    jwks_client = _get_jwks_client(discovery["jwks_uri"])
    try:
        signing_key = jwks_client.get_signing_key_from_jwt(id_token)
        alg = jwt.get_unverified_header(id_token).get("alg", "RS256")
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=[alg],
            audience=settings.oidc_client_id,
            issuer=settings.oidc_issuer_url,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid OIDC ID token: {exc}") from exc

    if claims.get("nonce") != expected_nonce:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="OIDC nonce mismatch (possible replay)")
    return claims


def _map_claims_to_user(claims: dict) -> User:
    settings = get_settings()
    valid_role_values = {r.value for r in Role}

    raw_roles = claims.get(settings.oidc_roles_claim) or []
    if isinstance(raw_roles, str):
        raw_roles = [raw_roles]
    roles = [Role(r) for r in raw_roles if r in valid_role_values]

    if not roles:
        default_values = [v.strip() for v in settings.oidc_default_roles.split(",") if v.strip()]
        roles = [Role(v) for v in default_values if v in valid_role_values] or [Role.VIEWER]

    subject = claims["sub"]
    email = claims.get("email") or f"{subject}@{settings.oidc_issuer_url}"
    display_name = claims.get("name") or claims.get("preferred_username") or email
    # Namespaced so an OIDC-issued subject can never collide with a dev-mode user_id.
    return User(user_id=f"oidc:{subject}", email=email, display_name=display_name, roles=roles)


async def handle_callback(*, code: str, state: str) -> User:
    _require_configured()
    settings = get_settings()
    state_payload = _decode_state(state)
    discovery = await _discover(settings.oidc_issuer_url)

    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(
            discovery["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.oidc_redirect_uri,
                "client_id": settings.oidc_client_id,
                "client_secret": settings.oidc_client_secret,
                "code_verifier": state_payload["code_verifier"],
            },
        )
    if token_resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"OIDC token exchange failed ({token_resp.status_code}): {token_resp.text}",
        )
    tokens = token_resp.json()
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="IdP token response missing id_token")

    claims = _validate_id_token(id_token, discovery=discovery, expected_nonce=state_payload["nonce"])
    return _map_claims_to_user(claims)
