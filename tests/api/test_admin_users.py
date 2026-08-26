"""Milestone 2: admin-provisioned User/Organization creation and the account-state
machine (docs/access-model.md §§1-2). The overriding invariant under test throughout
this file is that a `User` row can only ever be created by an authenticated
administrator hitting `POST /admin/users` -- never by an unauthenticated caller, never
by any other role, and never in any status but INVITED.
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
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _trader_headers(client) -> dict:
    login = client.post(
        "/api/v1/auth/login", json={"email": "trader@alphagasiq.local", "password": "trader-dev-password"}
    )
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _user_payload(**overrides) -> dict:
    payload = {
        "first_name": "Jane",
        "last_name": "Doe",
        "business_email": "jane.doe@realcompany.com",
        "company_name": "Real Energy Trading LLC",
        "company_website": "https://realenergytrading.example",
        "company_type": "Commodity Trading Firm",
        "job_title": "Senior Trader",
        "department": "Trading",
        "phone": "555-0100",
        "country": "United States",
        "state_region": "Texas",
        "primary_use_case": "Trading Research",
        "market_experience": "4-10 years",
        "role": "TRADER",
    }
    payload.update(overrides)
    return payload


def test_seeded_roles_are_the_eight_fixed_roles(client):
    r = client.get("/api/v1/admin/roles", headers=_admin_headers(client))
    assert r.status_code == 200
    names = {role["name"] for role in r.json()}
    assert names == {
        "SUPER_ADMIN",
        "ADMIN",
        "TRADER",
        "RISK_MANAGER",
        "RESEARCHER",
        "EXECUTIVE",
        "VIEWER",
        "API_USER",
    }


def test_admin_roles_requires_admin_role(client):
    r = client.get("/api/v1/admin/roles", headers=_trader_headers(client))
    assert r.status_code == 403


def test_admin_roles_requires_auth(client):
    r = client.get("/api/v1/admin/roles")
    assert r.status_code == 401


def test_admin_can_create_user_and_it_starts_invited(client):
    r = client.post("/api/v1/admin/users", json=_user_payload(), headers=_admin_headers(client))
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "INVITED"
    assert body["email"] == "jane.doe@realcompany.com"
    assert body["role_name"] == "TRADER"
    assert body["organization_name"] == "Real Energy Trading LLC"
    assert body["created_by"] == "u-admin-1"


def test_non_admin_cannot_create_user(client):
    r = client.post("/api/v1/admin/users", json=_user_payload(), headers=_trader_headers(client))
    assert r.status_code == 403


def test_unauthenticated_caller_cannot_create_user(client):
    r = client.post("/api/v1/admin/users", json=_user_payload())
    assert r.status_code == 401


def test_create_user_requesting_a_non_invited_status_is_ignored_not_honored(client):
    """There is no `status` field on `UserCreateRequest` at all -- this test pins that
    a client cannot smuggle an initial ACTIVE/SUSPENDED/etc. status past this
    endpoint by any request shape; every new account is INVITED, full stop."""
    payload = _user_payload(business_email="cant.skip.invited@realcompany.com")
    payload["status"] = "ACTIVE"  # not a recognized field; must be silently ignored
    r = client.post("/api/v1/admin/users", json=payload, headers=_admin_headers(client))
    assert r.status_code == 201
    assert r.json()["status"] == "INVITED"


def test_duplicate_email_is_rejected(client):
    headers = _admin_headers(client)
    payload = _user_payload(business_email="duplicate@realcompany.com")
    first = client.post("/api/v1/admin/users", json=payload, headers=headers)
    assert first.status_code == 201
    second = client.post("/api/v1/admin/users", json=payload, headers=headers)
    assert second.status_code == 409


def test_email_is_case_insensitively_deduplicated(client):
    headers = _admin_headers(client)
    client.post(
        "/api/v1/admin/users", json=_user_payload(business_email="MixedCase@RealCompany.com"), headers=headers
    )
    second = client.post(
        "/api/v1/admin/users", json=_user_payload(business_email="mixedcase@realcompany.com"), headers=headers
    )
    assert second.status_code == 409


def test_unknown_role_is_rejected(client):
    r = client.post(
        "/api/v1/admin/users",
        json=_user_payload(business_email="badrole@realcompany.com", role="NOT_A_REAL_ROLE"),
        headers=_admin_headers(client),
    )
    assert r.status_code == 400


def test_existing_organization_is_reused_not_duplicated(client):
    headers = _admin_headers(client)
    client.post(
        "/api/v1/admin/users",
        json=_user_payload(business_email="first@sharedcompany.com", company_name="Shared Energy Corp"),
        headers=headers,
    )
    client.post(
        "/api/v1/admin/users",
        json=_user_payload(business_email="second@sharedcompany.com", company_name="Shared Energy Corp"),
        headers=headers,
    )
    orgs = client.get("/api/v1/admin/organizations", headers=headers).json()
    matching = [o for o in orgs if o["name"] == "Shared Energy Corp"]
    assert len(matching) == 1

    users = client.get("/api/v1/admin/users", headers=headers).json()
    org_ids = {u["organization_id"] for u in users if u["organization_name"] == "Shared Energy Corp"}
    assert org_ids == {matching[0]["id"]}


def test_organization_create_endpoint_rejects_duplicate_name(client):
    headers = _admin_headers(client)
    body = {"name": "Standalone Org Co"}
    first = client.post("/api/v1/admin/organizations", json=body, headers=headers)
    assert first.status_code == 201
    second = client.post("/api/v1/admin/organizations", json=body, headers=headers)
    assert second.status_code == 409


def test_admin_users_list_and_get_round_trip(client):
    headers = _admin_headers(client)
    created = client.post(
        "/api/v1/admin/users", json=_user_payload(business_email="lookup@realcompany.com"), headers=headers
    ).json()

    listed = client.get("/api/v1/admin/users", headers=headers).json()
    assert any(u["id"] == created["id"] for u in listed)

    fetched = client.get(f"/api/v1/admin/users/{created['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["email"] == "lookup@realcompany.com"


def test_get_unknown_user_is_404(client):
    r = client.get("/api/v1/admin/users/does-not-exist", headers=_admin_headers(client))
    assert r.status_code == 404


def test_account_status_transition_suspend_then_reactivate(client):
    headers = _admin_headers(client)
    created = client.post(
        "/api/v1/admin/users", json=_user_payload(business_email="statuscheck@realcompany.com"), headers=headers
    ).json()
    user_id = created["id"]

    # INVITED -> ACTIVE is not an admin-facing transition (it only happens by
    # completing the magic-link invitation in Milestone 3), so this must be rejected.
    invalid = client.post(f"/api/v1/admin/users/{user_id}/status", json={"status": "ACTIVE"}, headers=headers)
    assert invalid.status_code == 400

    # But an admin can revoke an outstanding invitation outright.
    revoke = client.post(f"/api/v1/admin/users/{user_id}/status", json={"status": "REVOKED"}, headers=headers)
    assert revoke.status_code == 200
    assert revoke.json()["status"] == "REVOKED"

    # REVOKED is terminal -- nothing transitions out of it, not even back to ACTIVE.
    dead_end = client.post(f"/api/v1/admin/users/{user_id}/status", json={"status": "ACTIVE"}, headers=headers)
    assert dead_end.status_code == 400


def test_status_transition_requires_admin_role(client):
    headers = _admin_headers(client)
    created = client.post(
        "/api/v1/admin/users", json=_user_payload(business_email="statusauth@realcompany.com"), headers=headers
    ).json()
    r = client.post(
        f"/api/v1/admin/users/{created['id']}/status",
        json={"status": "REVOKED"},
        headers=_trader_headers(client),
    )
    assert r.status_code == 403
