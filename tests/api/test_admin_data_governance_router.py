"""Tenant-isolation retrofit (docs/alpha-intelligence.md section 11.1, Milestone
9): admin CRUD for `ModelRoutingPolicy`/`RetentionPolicy`, and the retention-purge
trigger endpoint."""

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


def test_non_admin_cannot_list_model_routing_policies(client):
    r = client.get("/api/v1/admin/model-routing-policies", headers=_trader_headers(client))
    assert r.status_code == 403


def test_admin_can_create_and_list_model_routing_policy(client):
    headers = _admin_headers(client)
    org_id = _create_org(client, headers)
    created = client.post(
        "/api/v1/admin/model-routing-policies",
        json={
            "organization_id": org_id,
            "data_classification": "CUSTOMER_RESTRICTED",
            "allow_external_llm_processing": True,
            "allowed_provider": "anthropic",
        },
        headers=headers,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["organization_id"] == org_id
    assert body["allow_external_llm_processing"] is True

    listed = client.get(
        "/api/v1/admin/model-routing-policies", params={"organization_id": org_id}, headers=headers
    ).json()
    assert any(p["id"] == body["id"] for p in listed)


def test_create_model_routing_policy_rejects_unknown_organization(client):
    headers = _admin_headers(client)
    r = client.post(
        "/api/v1/admin/model-routing-policies",
        json={
            "organization_id": "nonexistent",
            "data_classification": "CUSTOMER_RESTRICTED",
            "allow_external_llm_processing": True,
        },
        headers=headers,
    )
    assert r.status_code == 400


def test_admin_can_delete_model_routing_policy(client):
    headers = _admin_headers(client)
    org_id = _create_org(client, headers)
    created = client.post(
        "/api/v1/admin/model-routing-policies",
        json={
            "organization_id": org_id,
            "data_classification": "CUSTOMER_RESTRICTED",
            "allow_external_llm_processing": False,
        },
        headers=headers,
    ).json()
    deleted = client.delete(f"/api/v1/admin/model-routing-policies/{created['id']}", headers=headers)
    assert deleted.status_code == 204
    assert client.get("/api/v1/admin/model-routing-policies", headers=headers).json() == [] or all(
        p["id"] != created["id"] for p in client.get("/api/v1/admin/model-routing-policies", headers=headers).json()
    )


def test_delete_unknown_model_routing_policy_is_404(client):
    headers = _admin_headers(client)
    r = client.delete("/api/v1/admin/model-routing-policies/00000000-0000-0000-0000-000000000000", headers=headers)
    assert r.status_code == 404


def test_admin_can_create_and_list_retention_policy(client):
    headers = _admin_headers(client)
    org_id = _create_org(client, headers)
    created = client.post(
        "/api/v1/admin/retention-policies",
        json={"organization_id": org_id, "data_classification": "CUSTOMER_CONFIDENTIAL", "retention_days": 30},
        headers=headers,
    )
    assert created.status_code == 201
    assert created.json()["retention_days"] == 30

    listed = client.get(
        "/api/v1/admin/retention-policies", params={"organization_id": org_id}, headers=headers
    ).json()
    assert any(p["id"] == created.json()["id"] for p in listed)


def test_non_admin_cannot_create_retention_policy(client):
    r = client.post(
        "/api/v1/admin/retention-policies",
        json={"data_classification": "CUSTOMER_CONFIDENTIAL", "retention_days": 30},
        headers=_trader_headers(client),
    )
    assert r.status_code == 403


def test_apply_retention_with_no_policy_is_a_noop(client):
    headers = _admin_headers(client)
    org_id = _create_org(client, headers)
    r = client.post(
        "/api/v1/admin/retention-policies/apply",
        json={"organization_id": org_id, "data_classification": "CUSTOMER_CONFIDENTIAL"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["retention_days"] is None
    assert body["records_purged"] == 0


def test_apply_retention_purges_records_older_than_cutoff(client):
    """End-to-end: register a source/dataset, ingest a record, set a 0-day
    retention policy, and confirm apply_retention_policy purges it."""
    headers = _admin_headers(client)
    org_id = _create_org(client, headers)

    source = client.post(
        "/api/v1/admin/enterprise-data/sources",
        json={
            "organization_id": org_id,
            "name": "Well CSV",
            "connector_type": "MANUAL_UPLOAD",
            "classification": "CUSTOMER_CONFIDENTIAL",
        },
        headers=headers,
    ).json()
    dataset = client.post(
        f"/api/v1/admin/enterprise-data/sources/{source['id']}/datasets",
        json={"name": "Wells", "domain": "ASSET", "classification": "CUSTOMER_CONFIDENTIAL"},
        headers=headers,
    ).json()
    ingested = client.post(
        f"/api/v1/admin/enterprise-data/datasets/{dataset['id']}/ingest",
        json={"rows": [{"well_id": "W-1"}]},
        headers=headers,
    )
    assert ingested.status_code == 200

    policy = client.post(
        "/api/v1/admin/retention-policies",
        json={"organization_id": org_id, "data_classification": "CUSTOMER_CONFIDENTIAL", "retention_days": 0},
        headers=headers,
    )
    assert policy.status_code == 201

    applied = client.post(
        "/api/v1/admin/retention-policies/apply",
        json={"organization_id": org_id, "data_classification": "CUSTOMER_CONFIDENTIAL"},
        headers=headers,
    )
    assert applied.status_code == 200
    body = applied.json()
    assert body["retention_days"] == 0
    assert body["datasets_checked"] == 1
    assert body["records_purged"] == 1


def test_apply_retention_policies_for_all_organizations_covers_every_registered_pair(client):
    """Gap-closure item #4: scheduled retention purge cadence (docs/alpha-intelligence.md
    section 11.6 follow-up) -- `apply_retention_policies_for_all_organizations()` is what
    `worker.py`'s periodic loop calls instead of leaving purging admin/API-triggered only.
    Mirrors `test_generate_opportunities_for_all_organizations_covers_every_registered_org`
    (tests/api/test_alpha_enterprise_router.py)."""
    import asyncio

    from api_app import state as state_module

    headers = _admin_headers(client)
    org_id = _create_org(client, headers)

    source = client.post(
        "/api/v1/admin/enterprise-data/sources",
        json={
            "organization_id": org_id,
            "name": "Well CSV",
            "connector_type": "MANUAL_UPLOAD",
            "classification": "CUSTOMER_CONFIDENTIAL",
        },
        headers=headers,
    ).json()
    dataset = client.post(
        f"/api/v1/admin/enterprise-data/sources/{source['id']}/datasets",
        json={"name": "Wells", "domain": "ASSET", "classification": "CUSTOMER_CONFIDENTIAL"},
        headers=headers,
    ).json()
    ingested = client.post(
        f"/api/v1/admin/enterprise-data/datasets/{dataset['id']}/ingest",
        json={"rows": [{"well_id": "W-1"}]},
        headers=headers,
    )
    assert ingested.status_code == 200

    policy = client.post(
        "/api/v1/admin/retention-policies",
        json={"organization_id": org_id, "data_classification": "CUSTOMER_CONFIDENTIAL", "retention_days": 0},
        headers=headers,
    )
    assert policy.status_code == 201

    state = state_module._state
    results = asyncio.run(state.apply_retention_policies_for_all_organizations())
    assert len(results) == 1
    assert results[0]["organization_id"] == org_id
    assert results[0]["data_classification"] == "CUSTOMER_CONFIDENTIAL"
    assert results[0]["retention_days"] == 0
    assert results[0]["records_purged"] == 1


def test_apply_retention_policies_for_all_organizations_is_empty_with_no_registered_datasets(client):
    import asyncio

    from api_app import state as state_module

    state = state_module._state
    results = asyncio.run(state.apply_retention_policies_for_all_organizations())
    assert results == []
