"""Milestone 8 (docs/alpha-intelligence.md section 11.1): GET/POST/PATCH/DELETE
/admin/workspaces(/{id}) and workspace membership."""

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


def _create_org(client, headers) -> str:
    return client.post("/api/v1/admin/organizations", json={"name": "Acme Energy"}, headers=headers).json()["id"]


def test_workspaces_require_auth(client):
    assert client.get("/api/v1/admin/workspaces").status_code == 401


def test_trader_is_forbidden(client):
    r = client.get("/api/v1/admin/workspaces", headers=_trader_headers(client))
    assert r.status_code == 403


def test_create_and_list_workspace(client):
    headers = _admin_headers(client)
    org_id = _create_org(client, headers)

    r = client.post(
        "/api/v1/admin/workspaces", json={"organization_id": org_id, "name": "Trading Desk"}, headers=headers
    )
    assert r.status_code == 201
    workspace = r.json()
    assert workspace["name"] == "Trading Desk"

    listed = client.get("/api/v1/admin/workspaces", params={"organization_id": org_id}, headers=headers).json()
    assert len(listed) == 1


def test_create_workspace_unknown_org_is_400(client):
    headers = _admin_headers(client)
    r = client.post(
        "/api/v1/admin/workspaces", json={"organization_id": "nonexistent", "name": "X"}, headers=headers
    )
    assert r.status_code == 400


def test_get_update_delete_workspace(client):
    headers = _admin_headers(client)
    org_id = _create_org(client, headers)
    workspace = client.post(
        "/api/v1/admin/workspaces", json={"organization_id": org_id, "name": "Trading Desk"}, headers=headers
    ).json()
    workspace_id = workspace["id"]

    got = client.get(f"/api/v1/admin/workspaces/{workspace_id}", headers=headers)
    assert got.status_code == 200

    updated = client.patch(
        f"/api/v1/admin/workspaces/{workspace_id}", json={"name": "Renamed Desk"}, headers=headers
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed Desk"

    deleted = client.delete(f"/api/v1/admin/workspaces/{workspace_id}", headers=headers)
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/admin/workspaces/{workspace_id}", headers=headers).status_code == 404


def test_unknown_workspace_operations_are_404(client):
    headers = _admin_headers(client)
    assert client.get("/api/v1/admin/workspaces/nonexistent", headers=headers).status_code == 404
    assert client.patch("/api/v1/admin/workspaces/nonexistent", json={"name": "x"}, headers=headers).status_code == 404
    assert client.delete("/api/v1/admin/workspaces/nonexistent", headers=headers).status_code == 404


def test_membership_add_list_remove(client):
    headers = _admin_headers(client)
    org_id = _create_org(client, headers)
    workspace_id = client.post(
        "/api/v1/admin/workspaces", json={"organization_id": org_id, "name": "Trading Desk"}, headers=headers
    ).json()["id"]

    added = client.post(
        f"/api/v1/admin/workspaces/{workspace_id}/members", json={"user_id": "u-1"}, headers=headers
    )
    assert added.status_code == 201
    assert len(added.json()) == 1

    listed = client.get(f"/api/v1/admin/workspaces/{workspace_id}/members", headers=headers).json()
    assert listed[0]["user_id"] == "u-1"

    removed = client.delete(f"/api/v1/admin/workspaces/{workspace_id}/members/u-1", headers=headers)
    assert removed.status_code == 204
    assert client.get(f"/api/v1/admin/workspaces/{workspace_id}/members", headers=headers).json() == []
