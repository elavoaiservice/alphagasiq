"""Verifies `AppState` actually publishes real domain events at trade-lifecycle
moments through whatever `EventBus` it was built with — closing the gap where
`EventBus`/`InMemoryEventBus` existed but nothing in the app ever called `.publish()`.
Uses the default in-memory bus (`EVENT_BUS_IMPL=memory`) and inspects
`InMemoryEventBus.published` directly; `tests/eventbus/test_kafka_eventbus.py` covers
the Kafka-protocol implementation these same `AppState` call sites feed when
`EVENT_BUS_IMPL=redpanda` is configured instead.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from schemas import EventType


@pytest.fixture
def client():
    from api_app import state as state_module

    state_module.reset_app_state()
    from api_app.main import app

    with TestClient(app) as c:
        yield c
    state_module.reset_app_state()


def _published_types(client) -> list[str]:
    from api_app import state as state_module

    return [e.event_type.value for e in state_module._state.event_bus.published]


def test_boot_research_cycle_publishes_trade_idea_created(client):
    published = _published_types(client)
    assert EventType.TRADE_IDEA_CREATED.value in published


def test_approving_a_trade_publishes_trade_approved_or_rejected(client):
    from api_app import state as state_module

    admin_login = client.post(
        "/api/v1/auth/login", json={"email": "admin@alphagasiq.local", "password": "admin-dev-password"}
    )
    token = admin_login.json()["access_token"]

    approvals = client.get("/api/v1/approvals").json()
    approval = next(a for a in approvals if a["state"] == "HUMAN_REVIEW")
    r = client.post(
        f"/api/v1/approvals/{approval['id']}/action",
        json={"action": "APPROVE", "payload": {}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200

    published = _published_types(client)
    assert EventType.TRADE_APPROVED.value in published

    approval_events = [
        e
        for e in state_module._state.event_bus.published
        if e.event_type == EventType.TRADE_APPROVED
    ]
    assert approval_events[-1].payload["approval_id"] == approval["id"]


def test_full_close_lifecycle_publishes_position_updated(client):
    from api_app import state as state_module

    admin_login = client.post(
        "/api/v1/auth/login", json={"email": "admin@alphagasiq.local", "password": "admin-dev-password"}
    )
    token = admin_login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    approvals = client.get("/api/v1/approvals").json()
    approval = next(a for a in approvals if a["state"] == "HUMAN_REVIEW")
    client.post(f"/api/v1/approvals/{approval['id']}/action", json={"action": "APPROVE", "payload": {}}, headers=headers)

    trade_id = approval["trade_id"]
    close = client.post(f"/api/v1/trade-ideas/{trade_id}/close", json={}, headers=headers)
    assert close.status_code == 200

    published = _published_types(client)
    assert EventType.POSITION_UPDATED.value in published
