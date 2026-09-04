"""Milestone 2 (AlphaImpact): GET /alpha/impacts and GET /alpha/impacts/{id}."""

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


def _seed_impact_analysis(client):
    """Constructs a Signal + its ImpactAnalysis directly through the real
    alpha_service engines and repository, bypassing the date-sensitive research
    cycle -- exactly the pattern tests/api/trade_test_helpers.py established for
    trade ideas, applied here to Signal/ImpactAnalysis."""
    from alpha_service import ImpactEngine
    from api_app import state as state_module
    from schemas import Signal, SignalType

    state = state_module._state
    sig = Signal(
        signal_type=SignalType.STORAGE_CHANGE,
        category="fundamentals",
        headline="Storage forecast shifted",
        description="test signal",
        materiality_score=88.0,
        confidence=0.8,
    )
    asyncio.run(state.repo.save_signal(sig))
    analysis = ImpactEngine().analyze(sig)
    asyncio.run(state.repo.save_impact_analysis(analysis))
    return sig, analysis


def test_list_impacts_requires_auth(client):
    r = client.get("/api/v1/alpha/impacts")
    assert r.status_code == 401


def test_list_impacts_returns_200_with_permission(client):
    r = client.get("/api/v1/alpha/impacts", headers=_trader_headers(client))
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_get_unknown_impact_is_404(client):
    r = client.get("/api/v1/alpha/impacts/00000000-0000-0000-0000-000000000000", headers=_trader_headers(client))
    assert r.status_code == 404


def test_impact_analysis_is_retrievable_and_linked_to_its_signal(client):
    sig, analysis = _seed_impact_analysis(client)
    headers = _trader_headers(client)

    detail = client.get(f"/api/v1/alpha/impacts/{analysis.id}", headers=headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["signal_id"] == str(sig.id)
    assert len(body["chain"]) == 8  # STORAGE_CHANGE gets the full fundamentals chain

    listed = client.get("/api/v1/alpha/impacts", headers=headers)
    assert str(analysis.id) in [item["id"] for item in listed.json()]

    filtered = client.get(f"/api/v1/alpha/impacts?signal_id={sig.id}", headers=headers)
    assert [item["id"] for item in filtered.json()] == [str(analysis.id)]
