"""Milestone 3 (AlphaConsensus): GET /alpha/consensus, GET /alpha/consensus/{market},
and GET /alpha/consensus/by-id/{consensus_id}."""

from __future__ import annotations

import asyncio

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


def _seed_consensus_view(client):
    """Constructs a ConsensusView directly through the real alpha_service engines
    and repository, bypassing the date-sensitive research cycle -- the same pattern
    test_alpha_impacts_router.py established for Signal/ImpactAnalysis."""
    from alpha_service import ConsensusEngine
    from api_app import state as state_module
    from schemas import AgentForecast, AgentType, SignalDirection

    state = state_module._state
    forecasts = [
        AgentForecast(
            agent_id="storage-agent",
            agent_type=AgentType.STORAGE,
            agent_version="1.0.0",
            forecast_type="STORAGE_WEEKLY",
            target="STORAGE_BCF",
            forecast_value=88.0,
            direction=SignalDirection.BULLISH,
            probability=0.7,
            confidence=0.7,
        )
    ]
    view = ConsensusEngine().compute(
        consensus_type="STORAGE_FORECAST",
        target="STORAGE_BCF",
        market="HENRY_HUB",
        forecasts=forecasts,
        scores={},
        market_consensus_value=86.0,
    )
    asyncio.run(state.repo.save_consensus_view(view))
    return view


def test_list_consensus_requires_auth(client):
    r = client.get("/api/v1/alpha/consensus")
    assert r.status_code == 401


def test_list_consensus_returns_200_with_permission(client):
    r = client.get("/api/v1/alpha/consensus", headers=_trader_headers(client))
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_get_unknown_consensus_by_id_is_404(client):
    r = client.get(
        "/api/v1/alpha/consensus/by-id/00000000-0000-0000-0000-000000000000", headers=_trader_headers(client)
    )
    assert r.status_code == 404


def test_get_consensus_for_unknown_market_is_404(client):
    r = client.get("/api/v1/alpha/consensus/NO_SUCH_MARKET", headers=_trader_headers(client))
    assert r.status_code == 404


def test_consensus_view_is_retrievable_by_id_and_by_market(client):
    view = _seed_consensus_view(client)
    headers = _trader_headers(client)

    by_id = client.get(f"/api/v1/alpha/consensus/by-id/{view.id}", headers=headers)
    assert by_id.status_code == 200
    body = by_id.json()
    assert body["market"] == "HENRY_HUB"
    assert body["consensus_value"] == pytest.approx(88.0)
    assert body["market_consensus_value"] == pytest.approx(86.0)
    assert body["variance_vs_market"] == pytest.approx(2.0)

    by_market = client.get("/api/v1/alpha/consensus/HENRY_HUB", headers=headers)
    assert by_market.status_code == 200
    assert by_market.json()["id"] == str(view.id)

    listed = client.get("/api/v1/alpha/consensus", headers=headers)
    assert str(view.id) in [item["id"] for item in listed.json()]

    filtered = client.get("/api/v1/alpha/consensus?consensus_type=STORAGE_FORECAST", headers=headers)
    assert str(view.id) in [item["id"] for item in filtered.json()]
