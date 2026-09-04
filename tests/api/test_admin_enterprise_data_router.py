"""Milestone 8 (docs/alpha-intelligence.md section 11.3/11.4): the Enterprise
Data admin surface -- sources, test-connection, datasets, preview/ingest,
entitlements."""

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


def _create_source(client, headers, org_id) -> dict:
    return client.post(
        "/api/v1/admin/enterprise-data/sources",
        json={
            "organization_id": org_id,
            "name": "Well CSV",
            "connector_type": "MANUAL_UPLOAD",
            "classification": "CUSTOMER_CONFIDENTIAL",
        },
        headers=headers,
    ).json()


def test_sources_require_auth(client):
    assert client.get("/api/v1/admin/enterprise-data/sources").status_code == 401


def test_trader_is_forbidden(client):
    r = client.get("/api/v1/admin/enterprise-data/sources", headers=_trader_headers(client))
    assert r.status_code == 403


def test_create_source_unknown_org_is_400(client):
    headers = _admin_headers(client)
    r = client.post(
        "/api/v1/admin/enterprise-data/sources",
        json={"organization_id": "nonexistent", "name": "X", "connector_type": "MANUAL_UPLOAD", "classification": "PUBLIC"},
        headers=headers,
    )
    assert r.status_code == 400


def test_create_source_unknown_connector_type_is_400(client):
    headers = _admin_headers(client)
    org_id = _create_org(client, headers)
    r = client.post(
        "/api/v1/admin/enterprise-data/sources",
        json={"organization_id": org_id, "name": "X", "connector_type": "CARRIER_PIGEON", "classification": "PUBLIC"},
        headers=headers,
    )
    assert r.status_code == 400


def test_create_get_update_delete_source(client):
    headers = _admin_headers(client)
    org_id = _create_org(client, headers)
    source = _create_source(client, headers, org_id)
    assert source["status"] == "DRAFT"
    source_id = source["id"]

    got = client.get(f"/api/v1/admin/enterprise-data/sources/{source_id}", headers=headers)
    assert got.status_code == 200

    updated = client.patch(f"/api/v1/admin/enterprise-data/sources/{source_id}", json={"status": "ACTIVE"}, headers=headers)
    assert updated.status_code == 200
    assert updated.json()["status"] == "ACTIVE"

    deleted = client.delete(f"/api/v1/admin/enterprise-data/sources/{source_id}", headers=headers)
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/admin/enterprise-data/sources/{source_id}", headers=headers).status_code == 404


def test_test_connection_records_a_success_event_for_manual_upload(client):
    headers = _admin_headers(client)
    org_id = _create_org(client, headers)
    source_id = _create_source(client, headers, org_id)["id"]

    r = client.post(
        f"/api/v1/admin/enterprise-data/sources/{source_id}/test-connection",
        json={"sample_rows": [{"well_id": "W-1"}]},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "success"

    events = client.get(f"/api/v1/admin/enterprise-data/sources/{source_id}/events", headers=headers).json()
    assert len(events) == 1
    assert events[0]["event_type"] == "test_connection"


def test_test_connection_for_unimplemented_connector_reports_not_configured_as_error_event(client):
    headers = _admin_headers(client)
    org_id = _create_org(client, headers)
    source = client.post(
        "/api/v1/admin/enterprise-data/sources",
        json={"organization_id": org_id, "name": "REST source", "connector_type": "REST_API", "classification": "PUBLIC"},
        headers=headers,
    ).json()

    r = client.post(f"/api/v1/admin/enterprise-data/sources/{source['id']}/test-connection", json={}, headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "error"


def test_create_dataset_discovers_schema_from_sample_rows(client):
    headers = _admin_headers(client)
    org_id = _create_org(client, headers)
    source_id = _create_source(client, headers, org_id)["id"]

    r = client.post(
        f"/api/v1/admin/enterprise-data/sources/{source_id}/datasets",
        json={
            "name": "Well Production",
            "domain": "PRODUCTION",
            "classification": "CUSTOMER_CONFIDENTIAL",
            "sample_rows": [{"well_id": "W-1", "production_bbl": 100.5}],
        },
        headers=headers,
    )
    assert r.status_code == 201
    dataset = r.json()
    assert dataset["schema_summary"] == {"well_id": "string", "production_bbl": "number"}
    assert dataset["row_count"] == 0

    listed = client.get(f"/api/v1/admin/enterprise-data/sources/{source_id}/datasets", headers=headers).json()
    assert len(listed) == 1


def test_preview_and_ingest_dataset(client):
    headers = _admin_headers(client)
    org_id = _create_org(client, headers)
    source_id = _create_source(client, headers, org_id)["id"]
    dataset_id = client.post(
        f"/api/v1/admin/enterprise-data/sources/{source_id}/datasets",
        json={"name": "Well Production", "domain": "PRODUCTION", "classification": "CUSTOMER_CONFIDENTIAL"},
        headers=headers,
    ).json()["id"]

    preview = client.post(
        f"/api/v1/admin/enterprise-data/datasets/{dataset_id}/preview",
        json={"rows": [{"well_id": "W-1"}]},
        headers=headers,
    )
    assert preview.status_code == 200
    assert preview.json()["preview_rows"] == [{"well_id": "W-1"}]

    ingest = client.post(
        f"/api/v1/admin/enterprise-data/datasets/{dataset_id}/ingest",
        json={"rows": [{"well_id": "W-1"}, {"well_id": "W-2"}]},
        headers=headers,
    )
    assert ingest.status_code == 200
    body = ingest.json()
    assert body["rows_ingested"] == 2
    assert body["dataset"]["row_count"] == 2

    records = client.get(f"/api/v1/admin/enterprise-data/datasets/{dataset_id}/records", headers=headers).json()
    assert len(records) == 2

    events = client.get(f"/api/v1/admin/enterprise-data/sources/{source_id}/events", headers=headers).json()
    assert any(e["event_type"] == "ingest" for e in events)


def test_ingest_on_unimplemented_connector_is_400(client):
    headers = _admin_headers(client)
    org_id = _create_org(client, headers)
    source = client.post(
        "/api/v1/admin/enterprise-data/sources",
        json={"organization_id": org_id, "name": "REST source", "connector_type": "REST_API", "classification": "PUBLIC"},
        headers=headers,
    ).json()
    dataset_id = client.post(
        f"/api/v1/admin/enterprise-data/sources/{source['id']}/datasets",
        json={"name": "X", "domain": "MARKET_PRICE", "classification": "PUBLIC"},
        headers=headers,
    ).json()["id"]

    r = client.post(f"/api/v1/admin/enterprise-data/datasets/{dataset_id}/ingest", json={"rows": []}, headers=headers)
    assert r.status_code == 400


def test_entitlement_grant_list_revoke(client):
    headers = _admin_headers(client)
    org_id = _create_org(client, headers)
    source_id = _create_source(client, headers, org_id)["id"]
    dataset_id = client.post(
        f"/api/v1/admin/enterprise-data/sources/{source_id}/datasets",
        json={"name": "Well Production", "domain": "PRODUCTION", "classification": "CUSTOMER_CONFIDENTIAL"},
        headers=headers,
    ).json()["id"]

    granted = client.post(
        f"/api/v1/admin/enterprise-data/datasets/{dataset_id}/entitlements",
        json={"principal_type": "WORKSPACE", "principal_id": "ws-1"},
        headers=headers,
    )
    assert granted.status_code == 201
    entitlements = granted.json()
    assert len(entitlements) == 1
    entitlement_id = entitlements[0]["id"]

    listed = client.get(f"/api/v1/admin/enterprise-data/datasets/{dataset_id}/entitlements", headers=headers).json()
    assert len(listed) == 1

    revoked = client.delete(
        f"/api/v1/admin/enterprise-data/datasets/{dataset_id}/entitlements/{entitlement_id}", headers=headers
    )
    assert revoked.status_code == 204
    assert client.get(f"/api/v1/admin/enterprise-data/datasets/{dataset_id}/entitlements", headers=headers).json() == []


def test_unknown_source_and_dataset_operations_are_404(client):
    headers = _admin_headers(client)
    assert client.get("/api/v1/admin/enterprise-data/sources/nonexistent", headers=headers).status_code == 404
    assert client.get("/api/v1/admin/enterprise-data/datasets/nonexistent", headers=headers).status_code == 404
    assert client.get("/api/v1/admin/enterprise-data/sources/nonexistent/datasets", headers=headers).status_code == 404
    assert (
        client.post(
            "/api/v1/admin/enterprise-data/datasets/nonexistent/preview", json={"rows": []}, headers=headers
        ).status_code
        == 404
    )
