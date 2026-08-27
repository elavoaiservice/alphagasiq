"""Milestone 4 (AlphaScenario): GET /alpha/scenarios/library, POST /alpha/scenarios/run,
POST /alpha/scenarios/compare, GET /alpha/scenarios/runs(/{run_id})."""

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


def test_list_library_requires_auth(client):
    r = client.get("/api/v1/alpha/scenarios/library")
    assert r.status_code == 401


def test_list_library_returns_the_standing_catalog(client):
    r = client.get("/api/v1/alpha/scenarios/library", headers=_trader_headers(client))
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 14
    assert any(s["scenario_id"] == "freeport_lng_outage" for s in body)


def test_run_scenario_requires_auth(client):
    r = client.post("/api/v1/alpha/scenarios/run", json={"name": "x", "base_scenario_ids": ["freeport_lng_outage"]})
    assert r.status_code == 401


def test_run_named_scenario_returns_200(client):
    r = client.post(
        "/api/v1/alpha/scenarios/run",
        json={"name": "Freeport offline", "base_scenario_ids": ["freeport_lng_outage"]},
        headers=_trader_headers(client),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["scenario_name"] == "Freeport offline"
    assert body["price_shock_pct"] == pytest.approx(-0.18)
    assert "id" in body


def test_run_composed_scenario_stacks_custom_shock(client):
    r = client.post(
        "/api/v1/alpha/scenarios/run",
        json={
            "name": "Freeport + spike",
            "base_scenario_ids": ["freeport_lng_outage"],
            "variables": [{"factor_type": "PRICE_SHOCK_PCT", "value": 0.10}],
        },
        headers=_trader_headers(client),
    )
    assert r.status_code == 200
    assert r.json()["price_shock_pct"] == pytest.approx(-0.08)


def test_run_unknown_base_scenario_is_400(client):
    r = client.post(
        "/api/v1/alpha/scenarios/run",
        json={"name": "Bad", "base_scenario_ids": ["does_not_exist"]},
        headers=_trader_headers(client),
    )
    assert r.status_code == 400


def test_compare_runs_the_whole_standing_library(client):
    r = client.post("/api/v1/alpha/scenarios/compare", headers=_trader_headers(client))
    assert r.status_code == 200
    body = r.json()
    assert len(body["results"]) == 14
    assert body["comparison"]["worst_case_scenario_name"]


def test_scenario_run_is_retrievable_and_listed(client):
    headers = _trader_headers(client)
    run = client.post(
        "/api/v1/alpha/scenarios/run",
        json={"name": "Freeport offline", "base_scenario_ids": ["freeport_lng_outage"]},
        headers=headers,
    ).json()

    detail = client.get(f"/api/v1/alpha/scenarios/runs/{run['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["scenario_name"] == "Freeport offline"

    listed = client.get("/api/v1/alpha/scenarios/runs", headers=headers)
    assert run["id"] in [item["id"] for item in listed.json()]


def test_get_unknown_scenario_run_is_404(client):
    r = client.get(
        "/api/v1/alpha/scenarios/runs/00000000-0000-0000-0000-000000000000", headers=_trader_headers(client)
    )
    assert r.status_code == 404
