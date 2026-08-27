"""Milestone 6 (AlphaReplay): GET /alpha/replay."""

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


def _trader_headers(client) -> dict:
    login = client.post(
        "/api/v1/auth/login", json={"email": "trader@alphagasiq.local", "password": "trader-dev-password"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_replay_requires_auth(client):
    r = client.get("/api/v1/alpha/replay")
    assert r.status_code == 401


def test_replay_as_of_now_returns_current_model_retrospective(client):
    r = client.get("/api/v1/alpha/replay", headers=_trader_headers(client))
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "CURRENT_MODEL_RETROSPECTIVE"
    assert "price_observations" in body
    assert "signals" in body
    assert "impacts" in body
    assert "consensus_views" in body
    assert "scenario_runs" in body
    assert "memory_records" in body


def test_replay_before_any_data_existed_returns_empty_lists_not_fabricated_history(client):
    r = client.get(
        "/api/v1/alpha/replay",
        params={"as_of": "2000-01-01T00:00:00Z"},
        headers=_trader_headers(client),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["price_observations"] == []
    assert body["signals"] == []
    assert body["impacts"] == []
    assert body["consensus_views"] == []
    assert body["scenario_runs"] == []
    assert body["memory_records"] == []


def test_replay_reflects_a_scenario_run_that_already_happened(client):
    headers = _trader_headers(client)
    run = client.post(
        "/api/v1/alpha/scenarios/run",
        json={"name": "Freeport offline", "base_scenario_ids": ["freeport_lng_outage"]},
        headers=headers,
    ).json()

    r = client.get("/api/v1/alpha/replay", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert any(sr["id"] == run["id"] for sr in body["scenario_runs"])


def test_replay_market_filter_is_honored(client):
    headers = _trader_headers(client)
    r = client.get("/api/v1/alpha/replay", params={"market": "HENRY_HUB"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["market"] == "HENRY_HUB"
