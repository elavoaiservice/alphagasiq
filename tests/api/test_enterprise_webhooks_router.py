"""`POST /webhooks/enterprise-data/{source_id}` (apps/api/api_app/routers/
enterprise_webhooks.py): the public, HMAC-verified ingress a `WEBHOOK`-type
`EnterpriseDataSource` uses to receive inbound pushes, staged for an admin to
preview/ingest through the existing `/admin/enterprise-data` flow."""

from __future__ import annotations

import hashlib
import hmac
import json

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
    login = client.post("/api/v1/auth/login", json={"email": "admin@alphagasiq.local", "password": "admin-dev-password"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_org(client, headers) -> str:
    return client.post("/api/v1/admin/organizations", json={"name": "Acme Energy"}, headers=headers).json()["id"]


def _create_webhook_source(client, headers, org_id, *, signing_secret_env_var: str | None) -> dict:
    connection_config = {"signing_secret_env_var": signing_secret_env_var} if signing_secret_env_var else {}
    return client.post(
        "/api/v1/admin/enterprise-data/sources",
        json={
            "organization_id": org_id,
            "name": "Partner Webhook",
            "connector_type": "WEBHOOK",
            "classification": "CUSTOMER_CONFIDENTIAL",
            "connection_config": connection_config,
        },
        headers=headers,
    ).json()


def _sign(secret: str, raw_body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def test_webhook_rejects_push_when_source_has_no_signing_secret_configured(client):
    headers = _admin_headers(client)
    org_id = _create_org(client, headers)
    source_id = _create_webhook_source(client, headers, org_id, signing_secret_env_var=None)["id"]

    r = client.post(f"/api/v1/webhooks/enterprise-data/{source_id}", json={"rows": [{"a": 1}]})
    assert r.status_code == 400


def test_webhook_rejects_invalid_signature(client, monkeypatch):
    monkeypatch.setenv("PARTNER_WEBHOOK_SECRET", "real-secret")
    headers = _admin_headers(client)
    org_id = _create_org(client, headers)
    source_id = _create_webhook_source(client, headers, org_id, signing_secret_env_var="PARTNER_WEBHOOK_SECRET")["id"]

    r = client.post(
        f"/api/v1/webhooks/enterprise-data/{source_id}",
        json={"rows": [{"a": 1}]},
        headers={"X-AlphaGasIQ-Signature": "deadbeef"},
    )
    assert r.status_code == 401


def test_webhook_rejects_missing_signature_header(client, monkeypatch):
    monkeypatch.setenv("PARTNER_WEBHOOK_SECRET", "real-secret")
    headers = _admin_headers(client)
    org_id = _create_org(client, headers)
    source_id = _create_webhook_source(client, headers, org_id, signing_secret_env_var="PARTNER_WEBHOOK_SECRET")["id"]

    r = client.post(f"/api/v1/webhooks/enterprise-data/{source_id}", json={"rows": [{"a": 1}]})
    assert r.status_code == 401


def test_webhook_accepts_valid_signature_and_stages_rows_for_admin_ingest(client, monkeypatch):
    monkeypatch.setenv("PARTNER_WEBHOOK_SECRET", "real-secret")
    headers = _admin_headers(client)
    org_id = _create_org(client, headers)
    source_id = _create_webhook_source(client, headers, org_id, signing_secret_env_var="PARTNER_WEBHOOK_SECRET")["id"]

    raw_body = json.dumps({"rows": [{"well_id": "W-1"}, {"well_id": "W-2"}]}).encode("utf-8")
    signature = _sign("real-secret", raw_body)
    r = client.post(
        f"/api/v1/webhooks/enterprise-data/{source_id}",
        content=raw_body,
        headers={"X-AlphaGasIQ-Signature": signature, "Content-Type": "application/json"},
    )
    assert r.status_code == 202
    assert r.json()["staged"] == 2

    events = client.get(f"/api/v1/admin/enterprise-data/sources/{source_id}/events", headers=headers).json()
    assert any(e["event_type"] == "webhook_received" for e in events)

    dataset_id = client.post(
        f"/api/v1/admin/enterprise-data/sources/{source_id}/datasets",
        json={"name": "Partner Rows", "domain": "PRODUCTION", "classification": "CUSTOMER_CONFIDENTIAL"},
        headers=headers,
    ).json()["id"]

    test_connection = client.post(f"/api/v1/admin/enterprise-data/sources/{source_id}/test-connection", json={}, headers=headers)
    assert test_connection.json()["status"] == "success"

    preview = client.post(f"/api/v1/admin/enterprise-data/datasets/{dataset_id}/preview", json={}, headers=headers)
    assert preview.status_code == 200
    assert preview.json()["preview_rows"] == [{"well_id": "W-1"}, {"well_id": "W-2"}]

    ingest = client.post(f"/api/v1/admin/enterprise-data/datasets/{dataset_id}/ingest", json={}, headers=headers)
    assert ingest.status_code == 200
    assert ingest.json()["rows_ingested"] == 2

    # Rows were drained by ingest -- a second ingest sees nothing left staged.
    second_ingest = client.post(f"/api/v1/admin/enterprise-data/datasets/{dataset_id}/ingest", json={}, headers=headers)
    assert second_ingest.json()["rows_ingested"] == 0


def test_webhook_on_non_webhook_source_is_400(client):
    headers = _admin_headers(client)
    org_id = _create_org(client, headers)
    source_id = client.post(
        "/api/v1/admin/enterprise-data/sources",
        json={"organization_id": org_id, "name": "CSV", "connector_type": "MANUAL_UPLOAD", "classification": "PUBLIC"},
        headers=headers,
    ).json()["id"]

    r = client.post(f"/api/v1/webhooks/enterprise-data/{source_id}", json={"rows": []})
    assert r.status_code == 400


def test_webhook_unknown_source_is_404(client):
    r = client.post("/api/v1/webhooks/enterprise-data/nonexistent", json={"rows": []})
    assert r.status_code == 404
