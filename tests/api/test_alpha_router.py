"""Milestone 1 (AlphaSignal): GET /alpha/signals and GET /alpha/signals/{id}."""

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


def test_list_signals_requires_auth(client):
    r = client.get("/api/v1/alpha/signals")
    assert r.status_code == 401


def test_list_signals_returns_200_with_permission(client):
    r = client.get("/api/v1/alpha/signals", headers=_trader_headers(client))
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_get_unknown_signal_is_404(client):
    r = client.get(
        "/api/v1/alpha/signals/00000000-0000-0000-0000-000000000000", headers=_trader_headers(client)
    )
    assert r.status_code == 404


def test_signals_are_ranked_by_materiality_descending(client):
    """Submits a couple of directly-constructed signals through the real repository
    (bypassing the date-sensitive boot research cycle, exactly like
    tests/api/trade_test_helpers.py does for trade ideas) and asserts the endpoint
    returns them ranked highest-materiality-first."""
    import asyncio

    from api_app import state as state_module
    from schemas import Signal, SignalType

    state = state_module._state
    low = Signal(signal_type=SignalType.PRICE_MOVE, category="market", headline="low", description="low", materiality_score=61.0, confidence=0.6)
    high = Signal(signal_type=SignalType.STORAGE_CHANGE, category="fundamentals", headline="high", description="high", materiality_score=95.0, confidence=0.9)
    asyncio.run(state.repo.save_signal(low))
    asyncio.run(state.repo.save_signal(high))

    r = client.get("/api/v1/alpha/signals", headers=_trader_headers(client))
    assert r.status_code == 200
    body = r.json()
    ids_by_materiality = [item["id"] for item in body if item["id"] in (str(low.id), str(high.id))]
    assert ids_by_materiality == [str(high.id), str(low.id)]


def test_min_materiality_filter_excludes_lower_scores(client):
    import asyncio

    from api_app import state as state_module
    from schemas import Signal, SignalType

    state = state_module._state
    sig = Signal(signal_type=SignalType.PRICE_MOVE, category="market", headline="filtered", description="d", materiality_score=61.0, confidence=0.6)
    asyncio.run(state.repo.save_signal(sig))

    r = client.get("/api/v1/alpha/signals?min_materiality=90", headers=_trader_headers(client))
    assert r.status_code == 200
    assert str(sig.id) not in [item["id"] for item in r.json()]
