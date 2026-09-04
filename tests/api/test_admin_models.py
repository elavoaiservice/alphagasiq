"""Milestone 10: model management (spec §43, `docs/agent-governance.md` §6)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from api_app import state as state_module

    state_module.reset_app_state()
    from api_app.main import app

    with TestClient(app) as c:
        yield c
    state_module.reset_app_state()


def _admin_headers(client) -> dict:
    login = client.post(
        "/api/v1/auth/login", json={"email": "admin@alphagasiq.local", "password": "admin-dev-password"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _trader_headers(client) -> dict:
    login = client.post(
        "/api/v1/auth/login", json={"email": "trader@alphagasiq.local", "password": "trader-dev-password"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _extract_latest_token(client, email: str) -> str:
    from api_app import state as state_module

    sent = state_module._state.email_provider.sent
    message = next(m for m in reversed(sent) if m.to == email)
    return re.search(r"token=([A-Za-z0-9_-]+)", message.text_body).group(1)


def _super_admin_headers(client, email: str) -> dict:
    headers = _admin_headers(client)
    r = client.post(
        "/api/v1/admin/users",
        json={
            "first_name": "Sam",
            "last_name": "Root",
            "business_email": email,
            "company_name": f"Org for {email}",
            "role": "SUPER_ADMIN",
        },
        headers=headers,
    )
    assert r.status_code == 201
    token = _extract_latest_token(client, email)
    verify = client.get(f"/api/v1/auth/magic-link/verify?token={token}", follow_redirects=False)
    session_token = verify.headers["location"].split("access_token=", 1)[1]
    return {"Authorization": f"Bearer {session_token}"}


def test_boot_seeds_the_default_llm_model_as_approved(client):
    r = client.get("/api/v1/admin/models", headers=_super_admin_headers(client, "modeladmin1@realcompany.com"))
    assert r.status_code == 200
    models = r.json()
    assert len(models) == 1
    assert models[0]["status"] == "APPROVED"
    assert models[0]["model_name"] == "mock-llm-deterministic"


def test_list_models_requires_super_admin(client):
    r = client.get("/api/v1/admin/models", headers=_admin_headers(client))
    assert r.status_code == 403


def test_create_and_get_model(client):
    headers = _super_admin_headers(client, "modeladmin2@realcompany.com")
    r = client.post(
        "/api/v1/admin/models",
        json={"provider": "AnthropicLLMProvider", "model_name": "claude-test", "purpose": "evaluation"},
        headers=headers,
    )
    assert r.status_code == 201
    created = r.json()
    assert created["status"] == "AVAILABLE"

    fetched = client.get(f"/api/v1/admin/models/{created['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["model_name"] == "claude-test"


def test_get_unknown_model_is_404(client):
    r = client.get(
        "/api/v1/admin/models/no-such-model", headers=_super_admin_headers(client, "modeladmin3@realcompany.com")
    )
    assert r.status_code == 404


def test_update_model_status_and_reject_invalid_status(client):
    headers = _super_admin_headers(client, "modeladmin4@realcompany.com")
    created = client.post(
        "/api/v1/admin/models", json={"provider": "AnthropicLLMProvider", "model_name": "claude-test2"}, headers=headers
    ).json()

    r = client.patch(
        f"/api/v1/admin/models/{created['id']}/status",
        json={"status": "APPROVED", "reason": "Passed evaluation"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "APPROVED"

    r = client.patch(
        f"/api/v1/admin/models/{created['id']}/status", json={"status": "NOT_A_REAL_STATUS"}, headers=headers
    )
    assert r.status_code == 400


def test_agent_version_cannot_be_promoted_with_an_unapproved_model(client):
    headers = _super_admin_headers(client, "modeladmin5@realcompany.com")
    version = client.post(
        "/api/v1/admin/agents/SUPPLY/versions",
        json={"version": "9.9.9", "model_name": "not-yet-approved-model"},
        headers=headers,
    ).json()

    r = client.post(
        f"/api/v1/admin/agents/SUPPLY/versions/{version['id']}/transition",
        json={"status": "TESTING"},
        headers=headers,
    )
    assert r.status_code == 200

    r = client.post(
        f"/api/v1/admin/agents/SUPPLY/versions/{version['id']}/transition",
        json={"status": "APPROVED"},
        headers=headers,
    )
    assert r.status_code == 400
    assert "not an APPROVED model" in r.json()["detail"]
