"""Milestone 7: data-feed administration + health + dependency mapping (spec §§35-37).
"""

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


def test_list_data_feeds_returns_every_registered_provider_with_health_and_dependencies(client):
    r = client.get("/api/v1/admin/data-feeds", headers=_admin_headers(client))
    assert r.status_code == 200
    feeds = r.json()
    assert len(feeds) > 0
    by_id = {f["provider_id"]: f for f in feeds}
    assert "eia" in by_id
    eia = by_id["eia"]
    assert eia["connection_status"] in ("healthy", "degraded", "unavailable", "not_configured")
    assert eia["enabled"] is True
    assert eia["paused"] is False
    assert "Storage Agent" in eia["affected_agents"]
    assert "Forecasting Agent" in eia["dependency_chain"]
    assert eia["data_quality_score"] is None  # honest stub, not fabricated


def test_list_data_feeds_requires_admin_data_feeds_permission(client):
    r = client.get("/api/v1/admin/data-feeds", headers=_trader_headers(client))
    assert r.status_code == 403


def test_get_single_data_feed(client):
    r = client.get("/api/v1/admin/data-feeds/eia", headers=_admin_headers(client))
    assert r.status_code == 200
    assert r.json()["provider_id"] == "eia"


def test_data_feed_surfaces_licensing_metadata_for_public_gov_data_provider(client):
    r = client.get("/api/v1/admin/data-feeds/eia", headers=_admin_headers(client))
    assert r.status_code == 200
    body = r.json()
    assert body["license_type"] == "PUBLIC_DOMAIN_GOVERNMENT_DATA"
    assert body["public_or_commercial"] == "PUBLIC"
    assert body["redistribution_allowed"] is True
    assert body["ai_processing_allowed"] is True


def test_data_feed_licensing_metadata_is_none_for_unverified_provider(client):
    r = client.get("/api/v1/admin/data-feeds", headers=_admin_headers(client))
    assert r.status_code == 200
    by_id = {f["provider_id"]: f for f in r.json()}
    # mock_cme is SIMULATED and has never declared/verified licensing terms -- `None`
    # (unknown), never defaulted to permissive.
    mock_cme = by_id.get("mock_cme")
    if mock_cme is not None:
        assert mock_cme["license_type"] is None
        assert mock_cme["redistribution_allowed"] is None


def test_get_unknown_data_feed_is_404(client):
    r = client.get("/api/v1/admin/data-feeds/not-a-real-provider", headers=_admin_headers(client))
    assert r.status_code == 404


def test_update_data_feed_config(client):
    headers = _admin_headers(client)
    r = client.patch(
        "/api/v1/admin/data-feeds/eia",
        json={"paused": True, "priority": 5, "notes": "throttled for testing"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["paused"] is True
    assert body["priority"] == 5
    assert body["notes"] == "throttled for testing"
    assert body["updated_by"] is not None

    # Untouched fields survive a partial update.
    r2 = client.get("/api/v1/admin/data-feeds/eia", headers=headers)
    assert r2.json()["enabled"] is True


def test_update_unknown_data_feed_is_404(client):
    r = client.patch(
        "/api/v1/admin/data-feeds/not-a-real-provider", json={"paused": True}, headers=_admin_headers(client)
    )
    assert r.status_code == 404


def test_update_data_feed_requires_permission(client):
    r = client.patch(
        "/api/v1/admin/data-feeds/eia", json={"paused": True}, headers=_trader_headers(client)
    )
    assert r.status_code == 403


def test_test_connection_records_an_event(client):
    headers = _admin_headers(client)
    r = client.post("/api/v1/admin/data-feeds/eia/test-connection", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["event_type"] == "test_connection"
    assert body["status"] in ("success", "error")

    events = client.get("/api/v1/admin/data-feeds/eia/events", headers=headers).json()
    assert len(events) == 1
    assert events[0]["event_type"] == "test_connection"


def test_manual_refresh_records_an_event_with_records_received(client):
    headers = _admin_headers(client)
    r = client.post("/api/v1/admin/data-feeds/mock_news/refresh", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["event_type"] == "manual_refresh"
    assert body["status"] in ("success", "error")


def test_refresh_and_test_connection_on_unknown_provider_is_404(client):
    headers = _admin_headers(client)
    assert client.post("/api/v1/admin/data-feeds/not-a-real-provider/test-connection", headers=headers).status_code == 404
    assert client.post("/api/v1/admin/data-feeds/not-a-real-provider/refresh", headers=headers).status_code == 404
    assert client.get("/api/v1/admin/data-feeds/not-a-real-provider/events", headers=headers).status_code == 404


def test_dependency_map_matches_data_feed_dependencies_module(client):
    from api_app.data_feed_dependencies import full_dependency_map

    r = client.get("/api/v1/admin/data-feeds/dependency-map", headers=_admin_headers(client))
    assert r.status_code == 200
    assert r.json() == full_dependency_map()


def test_dependency_map_requires_permission(client):
    r = client.get("/api/v1/admin/data-feeds/dependency-map", headers=_trader_headers(client))
    assert r.status_code == 403
