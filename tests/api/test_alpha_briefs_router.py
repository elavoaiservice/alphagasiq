"""Milestone 7 (Overnight Intelligence Brief): GET /alpha/briefs, GET /alpha/briefs/latest,
GET /alpha/briefs/{id}."""

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


def test_briefs_require_auth(client):
    assert client.get("/api/v1/alpha/briefs").status_code == 401
    assert client.get("/api/v1/alpha/briefs/latest").status_code == 401


def test_latest_brief_is_generated_at_boot(client):
    r = client.get("/api/v1/alpha/briefs/latest", headers=_trader_headers(client))
    assert r.status_code == 200
    body = r.json()
    assert "headline" in body
    assert "summary" in body
    assert body["market"]


def test_list_returns_at_least_the_boot_generated_brief(client):
    r = client.get("/api/v1/alpha/briefs", headers=_trader_headers(client))
    assert r.status_code == 200
    body = r.json()
    assert len(body) >= 1


def test_brief_detail_is_retrievable_by_id(client):
    headers = _trader_headers(client)
    listed = client.get("/api/v1/alpha/briefs", headers=headers).json()
    brief_id = listed[0]["id"]

    r = client.get(f"/api/v1/alpha/briefs/{brief_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["id"] == brief_id


def test_unknown_brief_is_404(client):
    r = client.get(
        "/api/v1/alpha/briefs/00000000-0000-0000-0000-000000000000", headers=_trader_headers(client)
    )
    assert r.status_code == 404


def test_latest_for_a_market_with_no_brief_is_404(client):
    r = client.get(
        "/api/v1/alpha/briefs/latest",
        params={"market": "NO_SUCH_MARKET"},
        headers=_trader_headers(client),
    )
    assert r.status_code == 404
