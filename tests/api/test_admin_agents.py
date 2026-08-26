"""Milestone 8: AI Agent Control Center (spec §39, `docs/agent-governance.md` §§2-3)."""

from __future__ import annotations

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


def test_list_agents_covers_every_agent_type_with_catalog_and_stats(client):
    r = client.get("/api/v1/admin/agents", headers=_admin_headers(client))
    assert r.status_code == 200
    agents = r.json()
    assert len(agents) > 30  # every AgentType member
    by_type = {a["agent_type"]: a for a in agents}

    chief = by_type["CHIEF_TRADING_AGENT"]
    assert chief["implemented"] is True
    assert chief["administrable"] is True
    assert chief["team"] == "EXECUTIVE"
    assert chief["agent_id"] == "executive.chief_trading_agent.v1"
    assert chief["status"] == "ACTIVE"  # seeded default
    assert chief["total_executions"] >= 1  # boot's initial research cycle already ran it

    unimplemented = by_type["MARKET_DATA"]
    assert unimplemented["implemented"] is False
    assert unimplemented["administrable"] is False
    assert unimplemented["status"] is None
    assert unimplemented["total_executions"] == 0

    governor = by_type["RISK_GOVERNOR"]
    assert governor["implemented"] is True
    assert governor["administrable"] is False
    assert governor["status"] is None  # no AgentConfigRow -- visibility only


def test_list_agents_requires_admin_agent_management_permission(client):
    r = client.get("/api/v1/admin/agents", headers=_trader_headers(client))
    assert r.status_code == 403


def test_get_single_agent_detail_includes_recent_executions(client):
    r = client.get("/api/v1/admin/agents/CHIEF_TRADING_AGENT", headers=_admin_headers(client))
    assert r.status_code == 200
    body = r.json()
    assert body["agent_type"] == "CHIEF_TRADING_AGENT"
    assert "recent_executions" in body
    assert "recent_errors" in body


def test_get_unknown_agent_type_is_404(client):
    r = client.get("/api/v1/admin/agents/NOT_A_REAL_AGENT", headers=_admin_headers(client))
    assert r.status_code == 404


def test_update_agent_config(client):
    headers = _admin_headers(client)
    r = client.patch(
        "/api/v1/admin/agents/SUPPLY",
        json={"status": "PAUSED", "confidence_threshold": 0.7, "notes": "under review"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "PAUSED"
    assert body["confidence_threshold"] == 0.7
    assert body["notes"] == "under review"
    assert body["updated_by"] is not None


def test_update_agent_rejects_invalid_status(client):
    r = client.patch(
        "/api/v1/admin/agents/SUPPLY", json={"status": "NOT_A_REAL_STATUS"}, headers=_admin_headers(client)
    )
    assert r.status_code == 400


def test_update_risk_governor_is_rejected(client):
    r = client.patch(
        "/api/v1/admin/agents/RISK_GOVERNOR", json={"status": "PAUSED"}, headers=_admin_headers(client)
    )
    assert r.status_code == 400


def test_update_unimplemented_agent_is_rejected(client):
    r = client.patch(
        "/api/v1/admin/agents/MARKET_DATA", json={"status": "PAUSED"}, headers=_admin_headers(client)
    )
    assert r.status_code == 400


def test_update_unknown_agent_type_is_404(client):
    r = client.patch(
        "/api/v1/admin/agents/NOT_A_REAL_AGENT", json={"status": "PAUSED"}, headers=_admin_headers(client)
    )
    assert r.status_code == 404


def test_update_agent_requires_permission(client):
    r = client.patch(
        "/api/v1/admin/agents/SUPPLY", json={"status": "PAUSED"}, headers=_trader_headers(client)
    )
    assert r.status_code == 403


def test_run_chief_trading_agent_succeeds(client):
    r = client.post("/api/v1/admin/agents/CHIEF_TRADING_AGENT/run", headers=_admin_headers(client))
    assert r.status_code == 200
    assert "trade_ideas_generated" in r.json()


def test_run_paused_chief_trading_agent_is_rejected(client):
    headers = _admin_headers(client)
    client.patch("/api/v1/admin/agents/CHIEF_TRADING_AGENT", json={"status": "PAUSED"}, headers=headers)
    r = client.post("/api/v1/admin/agents/CHIEF_TRADING_AGENT/run", headers=headers)
    assert r.status_code == 409


def test_run_sub_agent_is_honestly_rejected_not_faked(client):
    r = client.post("/api/v1/admin/agents/SUPPLY/run", headers=_admin_headers(client))
    assert r.status_code == 409
    assert "Chief Trading Agent" in r.json()["detail"]


def test_run_unimplemented_agent_is_404(client):
    r = client.post("/api/v1/admin/agents/MARKET_DATA/run", headers=_admin_headers(client))
    assert r.status_code == 404


def test_run_agent_requires_permission(client):
    r = client.post("/api/v1/admin/agents/CHIEF_TRADING_AGENT/run", headers=_trader_headers(client))
    assert r.status_code == 403


def test_existing_chief_trading_run_endpoint_still_works_after_refactor(client):
    r = client.post(
        "/api/v1/agents/chief-trading/run",
        headers={"Authorization": _admin_headers(client)["Authorization"]},
    )
    assert r.status_code == 200
    assert "trade_ideas_generated" in r.json()
