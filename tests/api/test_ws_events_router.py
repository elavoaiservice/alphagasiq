"""Gap-closure item #1 (docs/alpha-intelligence.md section 11.8): `GET /ws/events`
forwards dashboard-relevant `DomainEvent`s published on `state.event_bus`, filtered
to what the connected caller can see -- proves a subscribed connection receives an
event for its own organization, does not receive one for another organization, and
that a missing/invalid token is rejected before the socket is accepted."""

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


def _login(client, *, email="trader@alphagasiq.local", password="trader-dev-password") -> str:
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return res.json()["access_token"]


def _patch_scope(monkeypatch, *, organization_id, unrestricted):
    from api_app.routers import ws as ws_router

    async def fake_scope(_user, _state):
        return organization_id, unrestricted

    monkeypatch.setattr(ws_router, "resolve_organization_scope", fake_scope)


def _publish_signal(client, *, organization_id: str | None, headline: str):
    from schemas import DomainEvent, EventType, Signal, SignalType

    from api_app.state import get_app_state

    signal = Signal(
        signal_type=SignalType.PRICE_MOVE,
        category="market",
        headline=headline,
        description="d",
        materiality_score=80.0,
        confidence=0.8,
        organization_id=organization_id,
    )

    async def _do():
        state = await get_app_state()
        await state.event_bus.publish(
            DomainEvent(
                event_type=EventType.SIGNAL_DETECTED,
                source_service="test",
                payload=signal.model_dump(mode="json"),
            )
        )

    client.portal.call(_do)


def test_connection_rejected_without_token(client):
    from starlette.testclient import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/ws/events"):
            pass


def test_connection_rejected_with_invalid_token(client):
    from starlette.testclient import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/ws/events?token=not-a-real-token"):
            pass


def test_subscriber_receives_event_for_own_organization(client, monkeypatch):
    _patch_scope(monkeypatch, organization_id="org-a", unrestricted=False)
    token = _login(client)
    with client.websocket_connect(f"/api/v1/ws/events?token={token}") as ws:
        _publish_signal(client, organization_id="org-a", headline="org-a-signal")
        message = ws.receive_json()
    assert message["event_type"] == "SIGNAL_DETECTED"
    assert message["payload"]["headline"] == "org-a-signal"


def test_subscriber_does_not_receive_event_for_another_organization(client, monkeypatch):
    _patch_scope(monkeypatch, organization_id="org-a", unrestricted=False)
    token = _login(client)
    with client.websocket_connect(f"/api/v1/ws/events?token={token}") as ws:
        _publish_signal(client, organization_id="org-b", headline="org-b-signal")
        _publish_signal(client, organization_id="org-a", headline="org-a-signal")
        message = ws.receive_json()
    # Only the org-a event should ever reach this connection -- the org-b one was
    # filtered out server-side, not merely received second.
    assert message["payload"]["headline"] == "org-a-signal"


def test_platform_wide_event_reaches_every_subscriber(client, monkeypatch):
    _patch_scope(monkeypatch, organization_id="org-a", unrestricted=False)
    token = _login(client)
    with client.websocket_connect(f"/api/v1/ws/events?token={token}") as ws:
        _publish_signal(client, organization_id=None, headline="platform-wide-signal")
        message = ws.receive_json()
    assert message["payload"]["headline"] == "platform-wide-signal"
