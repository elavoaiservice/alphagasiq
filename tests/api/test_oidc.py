"""Real OIDC (Authorization Code + PKCE) tests.

Exercises `api_app.oidc` through the actual `/auth/oidc/*` HTTP endpoints, with only
the network boundary (the IdP's discovery/token HTTP calls and its JWKS lookup)
replaced by test doubles — everything else (PKCE generation/verification, the signed
state token, real RS256 signature verification via `jwt.decode`, nonce replay
protection, and claims-to-`Role` mapping) runs for real. This is the platform's only
real cryptographic auth path (the dev-mode password grant needs no such test since it
never talks to an external IdP).
"""

from __future__ import annotations

import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from api_app import oidc as oidc_module
from config import get_settings
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api_app import state as state_module

    state_module.reset_app_state()
    from api_app.main import app

    with TestClient(app) as c:
        yield c
    state_module.reset_app_state()


def test_auth_mode_reports_not_configured_by_default(client):
    r = client.get("/api/v1/auth/mode")
    assert r.status_code == 200
    assert r.json() == {"oidc_configured": False}


def test_oidc_login_is_501_when_not_configured(client):
    r = client.get("/api/v1/auth/oidc/login", follow_redirects=False)
    assert r.status_code == 501


def test_oidc_callback_is_501_when_not_configured(client):
    r = client.get("/api/v1/auth/oidc/callback", params={"code": "x", "state": "y"}, follow_redirects=False)
    assert r.status_code == 501


@pytest.fixture
def configured_oidc(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "oidc_issuer_url", "https://idp.test")
    monkeypatch.setattr(settings, "oidc_client_id", "test-client-id")
    monkeypatch.setattr(settings, "oidc_client_secret", "test-client-secret")
    monkeypatch.setattr(settings, "oidc_redirect_uri", "http://localhost:8000/api/v1/auth/oidc/callback")
    monkeypatch.setattr(settings, "cors_origins", "http://localhost:3000")
    oidc_module._discovery_cache.clear()
    oidc_module._jwks_client_cache.clear()
    yield settings
    oidc_module._discovery_cache.clear()
    oidc_module._jwks_client_cache.clear()


def test_auth_mode_reports_configured(client, configured_oidc):
    r = client.get("/api/v1/auth/mode")
    assert r.json() == {"oidc_configured": True}


_DISCOVERY_DOC = {
    "authorization_endpoint": "https://idp.test/authorize",
    "token_endpoint": "https://idp.test/token",
    "jwks_uri": "https://idp.test/jwks",
}


class _FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code
        self.text = json.dumps(json_data)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)

    def json(self):
        return self._json


def _install_fake_idp(monkeypatch, *, token_response_builder):
    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, *args, **kwargs):
            assert url == "https://idp.test/.well-known/openid-configuration"
            return _FakeResponse(_DISCOVERY_DOC)

        async def post(self, url, *args, **kwargs):
            assert url == _DISCOVERY_DOC["token_endpoint"]
            return _FakeResponse(token_response_builder(kwargs.get("data", {})))

    monkeypatch.setattr(oidc_module.httpx, "AsyncClient", _FakeAsyncClient)


class _FakeSigningKey:
    def __init__(self, key):
        self.key = key


def _install_fake_jwks(monkeypatch, public_key):
    class _FakeJwksClient:
        def get_signing_key_from_jwt(self, token):
            return _FakeSigningKey(public_key)

    monkeypatch.setattr(oidc_module, "_get_jwks_client", lambda jwks_uri: _FakeJwksClient())


def _do_login(client) -> dict:
    """Drives GET /auth/oidc/login and returns the PKCE/nonce/state values the IdP
    redirect carried, exactly as a real IdP would receive them on its /authorize
    endpoint."""
    resp = client.get("/api/v1/auth/oidc/login", follow_redirects=False)
    assert resp.status_code in (302, 307)
    location = resp.headers["location"]
    assert urlparse(location).netloc == "idp.test"
    qs = parse_qs(urlparse(location).query)
    assert qs["code_challenge_method"][0] == "S256"
    assert qs["response_type"][0] == "code"
    return {"nonce": qs["nonce"][0], "code_challenge": qs["code_challenge"][0], "state": qs["state"][0]}


def test_full_oidc_login_and_callback_flow_maps_claims_and_issues_session(client, configured_oidc, monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    captured: dict = {}

    def build_token_response(posted_data):
        verifier = posted_data["code_verifier"]
        challenge = oidc_module._b64url(hashlib.sha256(verifier.encode("ascii")).digest())
        assert challenge == captured["code_challenge"], "PKCE verifier must hash to the original code_challenge"
        assert posted_data["code"] == "test-auth-code"
        assert posted_data["client_id"] == "test-client-id"
        assert posted_data["client_secret"] == "test-client-secret"
        assert posted_data["redirect_uri"] == "http://localhost:8000/api/v1/auth/oidc/callback"

        id_token = jwt.encode(
            {
                "iss": "https://idp.test",
                "aud": "test-client-id",
                "sub": "auth0|abc123",
                "email": "trader@realcompany.com",
                "name": "Real SSO Trader",
                "nonce": captured["nonce"],
                "roles": ["TRADER", "RESEARCHER"],
                "exp": time.time() + 300,
            },
            private_key,
            algorithm="RS256",
            headers={"kid": "test-kid"},
        )
        return {"access_token": "irrelevant-resource-token", "id_token": id_token, "token_type": "Bearer"}

    _install_fake_idp(monkeypatch, token_response_builder=build_token_response)
    _install_fake_jwks(monkeypatch, public_key)

    login_values = _do_login(client)
    captured.update(login_values)

    callback_resp = client.get(
        "/api/v1/auth/oidc/callback",
        params={"code": "test-auth-code", "state": login_values["state"]},
        follow_redirects=False,
    )
    assert callback_resp.status_code in (302, 307)
    redirect_location = callback_resp.headers["location"]
    assert redirect_location.startswith("http://localhost:3000/#access_token=")
    session_token = redirect_location.split("access_token=", 1)[1]

    # This platform's own session JWT is indistinguishable downstream from a dev-mode
    # login's — every router's require_role/get_current_user needs no OIDC awareness.
    me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {session_token}"})
    assert me_resp.status_code == 200
    body = me_resp.json()
    assert body["email"] == "trader@realcompany.com"
    assert body["display_name"] == "Real SSO Trader"
    assert set(body["roles"]) == {"TRADER", "RESEARCHER"}
    assert body["user_id"] == "oidc:auth0|abc123"


def test_unrecognized_role_claims_fall_back_to_default_viewer_role(client, configured_oidc, monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    captured: dict = {}

    def build_token_response(posted_data):
        id_token = jwt.encode(
            {
                "iss": "https://idp.test",
                "aud": "test-client-id",
                "sub": "auth0|no-roles",
                "email": "someone@realcompany.com",
                "nonce": captured["nonce"],
                "roles": ["some-unrelated-idp-group"],
                "exp": time.time() + 300,
            },
            private_key,
            algorithm="RS256",
            headers={"kid": "test-kid"},
        )
        return {"access_token": "x", "id_token": id_token}

    _install_fake_idp(monkeypatch, token_response_builder=build_token_response)
    _install_fake_jwks(monkeypatch, public_key)

    login_values = _do_login(client)
    captured.update(login_values)
    callback_resp = client.get(
        "/api/v1/auth/oidc/callback",
        params={"code": "test-auth-code", "state": login_values["state"]},
        follow_redirects=False,
    )
    session_token = callback_resp.headers["location"].split("access_token=", 1)[1]

    me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {session_token}"})
    assert me_resp.json()["roles"] == ["VIEWER"], "never grant an elevated role from an unrecognized claim"


def test_id_token_with_wrong_nonce_is_rejected_as_replay(client, configured_oidc, monkeypatch):
    """The nonce a real IdP echoes back must match the one this platform generated at
    /login time — otherwise a captured authorization code/id_token from a *different*
    login attempt could be replayed. This is our own logic (not something `jwt.decode`
    checks), so it needs its own test."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    def build_token_response(posted_data):
        id_token = jwt.encode(
            {
                "iss": "https://idp.test",
                "aud": "test-client-id",
                "sub": "auth0|abc123",
                "email": "trader@realcompany.com",
                "nonce": "a-completely-different-nonce",
                "roles": ["TRADER"],
                "exp": time.time() + 300,
            },
            private_key,
            algorithm="RS256",
            headers={"kid": "test-kid"},
        )
        return {"access_token": "x", "id_token": id_token}

    _install_fake_idp(monkeypatch, token_response_builder=build_token_response)
    _install_fake_jwks(monkeypatch, public_key)

    login_values = _do_login(client)
    callback_resp = client.get(
        "/api/v1/auth/oidc/callback",
        params={"code": "test-auth-code", "state": login_values["state"]},
        follow_redirects=False,
    )
    assert callback_resp.status_code == 401


def test_id_token_signed_by_wrong_key_is_rejected(client, configured_oidc, monkeypatch):
    """A token signed by any key other than the one the (fake) JWKS endpoint actually
    serves must fail signature verification — proves `jwt.decode` is really checking
    the signature here, not just parsing the payload."""
    real_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    captured: dict = {}

    def build_token_response(posted_data):
        id_token = jwt.encode(
            {
                "iss": "https://idp.test",
                "aud": "test-client-id",
                "sub": "auth0|abc123",
                "email": "trader@realcompany.com",
                "nonce": captured["nonce"],
                "roles": ["TRADER"],
                "exp": time.time() + 300,
            },
            attacker_key,  # signed by the wrong key
            algorithm="RS256",
            headers={"kid": "test-kid"},
        )
        return {"access_token": "x", "id_token": id_token}

    _install_fake_idp(monkeypatch, token_response_builder=build_token_response)
    _install_fake_jwks(monkeypatch, real_key.public_key())  # JWKS serves the real key

    login_values = _do_login(client)
    captured.update(login_values)
    callback_resp = client.get(
        "/api/v1/auth/oidc/callback",
        params={"code": "test-auth-code", "state": login_values["state"]},
        follow_redirects=False,
    )
    assert callback_resp.status_code == 401
