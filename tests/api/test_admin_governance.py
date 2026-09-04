"""Milestone 10: risk settings, audit logging, and system health/alerts
(spec §§44/55/56, `docs/agent-governance.md` §§6-8)."""

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


# -- risk settings ----------------------------------------------------------------------


def test_get_and_update_risk_settings(client):
    headers = _super_admin_headers(client, "riskadmin1@realcompany.com")
    r = client.get("/api/v1/admin/risk-settings", headers=headers)
    assert r.status_code == 200
    before = r.json()

    r = client.put(
        "/api/v1/admin/risk-settings",
        json={
            "max_position_size": before["max_position_size"] + 100,
            "max_risk_per_trade": before["max_risk_per_trade"],
            "max_daily_loss": before["max_daily_loss"],
            "max_drawdown": before["max_drawdown"],
            "max_portfolio_var": before["max_portfolio_var"],
            "max_sector_exposure": before["max_sector_exposure"],
            "max_contract_exposure": before["max_contract_exposure"],
            "max_correlated_exposure": before["max_correlated_exposure"],
            "reason": "Increasing position limits ahead of winter contracting season",
        },
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["max_position_size"] == before["max_position_size"] + 100

    logs = client.get("/api/v1/admin/audit-logs", headers=headers).json()
    assert any(e["action"] == "risk_settings.update" for e in logs)


def test_update_risk_settings_requires_a_reason(client):
    headers = _super_admin_headers(client, "riskadmin2@realcompany.com")
    before = client.get("/api/v1/admin/risk-settings", headers=headers).json()
    before["reason"] = "   "
    r = client.put("/api/v1/admin/risk-settings", json=before, headers=headers)
    assert r.status_code == 400


def test_risk_settings_requires_super_admin(client):
    r = client.get("/api/v1/admin/risk-settings", headers=_admin_headers(client))
    assert r.status_code == 403


# -- audit log ----------------------------------------------------------------------------


def test_audit_log_records_agent_status_changes(client):
    headers = _admin_headers(client)
    client.patch("/api/v1/admin/agents/SUPPLY", json={"status": "PAUSED"}, headers=headers)

    logs = client.get("/api/v1/admin/audit-logs", headers=headers).json()
    assert any(e["action"] == "agent.status_change" and e["resource_id"] == "SUPPLY" for e in logs)

    filtered = client.get("/api/v1/admin/audit-logs?resource_type=agent", headers=headers).json()
    assert all(e["resource_type"] == "agent" for e in filtered)
    assert len(filtered) >= 1


def test_audit_log_requires_permission(client):
    r = client.get("/api/v1/admin/audit-logs", headers=_trader_headers(client))
    assert r.status_code == 403


# -- system health ------------------------------------------------------------------------


def test_system_health_reports_real_subsystem_status(client):
    r = client.get("/api/v1/admin/system-health", headers=_admin_headers(client))
    assert r.status_code == 200
    body = r.json()
    assert body["data_feeds"]["total"] > 0
    assert body["agents"]["total_administrable"] > 0
    assert body["models"]["total"] >= 1
    assert body["risk_governor"]["status"] == "operational"
    assert "implementation" in body["event_bus"]


def test_system_health_requires_permission(client):
    r = client.get("/api/v1/admin/system-health", headers=_trader_headers(client))
    assert r.status_code == 403
