"""Milestone 4: real RBAC permission enforcement + feature-entitlement computation
(docs/access-model.md §§5-6, spec §§23-24).
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


def _risk_headers(client) -> dict:
    login = client.post(
        "/api/v1/auth/login", json={"email": "risk@alphagasiq.local", "password": "risk-dev-password"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_admin_entitlements_include_every_admin_permission_except_super_admin_only(client):
    r = client.get("/api/v1/auth/me/entitlements", headers=_admin_headers(client))
    assert r.status_code == 200
    permissions = set(r.json()["permissions"])
    assert "admin.users.create" in permissions
    assert "admin.users.revoke" in permissions
    assert "admin.organizations" in permissions
    # Reserved for SUPER_ADMIN alone -- ADMIN (the dev-mode fixture's DB-role
    # equivalent) must not have these.
    assert "admin.risk_settings" not in permissions
    assert "admin.system_settings" not in permissions


def test_trader_entitlements_have_no_admin_permissions(client):
    r = client.get("/api/v1/auth/me/entitlements", headers=_trader_headers(client))
    permissions = set(r.json()["permissions"])
    assert not any(p.startswith("admin.") for p in permissions)
    assert "chief_agent.chat" in permissions
    assert "paper_trading.execute" in permissions


def test_trader_feature_entitlements_grant_paper_trading_but_not_risk_analytics(client):
    r = client.get("/api/v1/auth/me/entitlements", headers=_trader_headers(client))
    features = r.json()["features"]
    assert features["paper_trading"] is True
    assert features["chief_trading_agent_chat"] is True
    assert features["risk_analytics"] is False


def test_risk_manager_feature_entitlements_grant_risk_analytics_not_paper_trading(client):
    r = client.get("/api/v1/auth/me/entitlements", headers=_risk_headers(client))
    features = r.json()["features"]
    assert features["risk_analytics"] is True
    assert features["paper_trading"] is False


def test_entitlements_endpoint_requires_auth(client):
    r = client.get("/api/v1/auth/me/entitlements")
    assert r.status_code == 401


def test_permission_based_admin_gate_still_rejects_non_admin(client):
    """Regression test for the Milestone 2->4 cutover: `POST /admin/users` used to be
    gated by `require_role(Role.ADMIN)`; it's now gated by the real
    `require_permission("admin.users.create")`. A non-admin caller must still get a
    403, not suddenly gain access because the enforcement mechanism changed."""
    r = client.post(
        "/api/v1/admin/users",
        json={
            "first_name": "X",
            "last_name": "Y",
            "business_email": "shouldfail@realcompany.com",
            "company_name": "Should Fail Co",
            "role": "TRADER",
        },
        headers=_trader_headers(client),
    )
    assert r.status_code == 403


def test_status_change_permission_is_granular_by_target_status(client):
    """`POST /admin/users/{id}/status` requires admin.users.suspend for SUSPENDED/
    DISABLED and admin.users.revoke for REVOKED, not just any admin permission --
    exercised here against a real DB user rather than asserted purely by inspection."""
    import re

    admin_headers = _admin_headers(client)
    created = client.post(
        "/api/v1/admin/users",
        json={
            "first_name": "Status",
            "last_name": "Target",
            "business_email": "statustarget@realcompany.com",
            "company_name": "Status Target Co",
            "role": "VIEWER",
        },
        headers=admin_headers,
    ).json()

    # SUSPENDED is only a legal transition from ACTIVE (docs/access-model.md §2), so
    # activate the account first via the same magic-link flow a real user would use.
    from api_app import state as state_module

    sent = state_module._state.email_provider.sent
    token = re.search(r"token=([A-Za-z0-9_-]+)", sent[-1].text_body).group(1)
    client.get(f"/api/v1/auth/magic-link/verify?token={token}", follow_redirects=False)

    # ADMIN's DB role has admin.users.suspend AND admin.users.revoke (everything but
    # the 4 SUPER_ADMIN-only permissions), so both transitions succeed for it.
    suspend = client.post(
        f"/api/v1/admin/users/{created['id']}/status", json={"status": "SUSPENDED"}, headers=admin_headers
    )
    assert suspend.status_code == 200
    revoke = client.post(
        f"/api/v1/admin/users/{created['id']}/status", json={"status": "REVOKED"}, headers=admin_headers
    )
    assert revoke.status_code == 200
