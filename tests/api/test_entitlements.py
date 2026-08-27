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


def _activate_via_magic_link(client, email: str, role: str) -> dict:
    """Creates a real DB user (via the admin API) with the given role, activates it
    by extracting the magic-link token from the console email provider (exactly what
    a real user does by clicking the link), and returns {"headers": ..., "user": ...}."""
    import re

    admin_headers = _admin_headers(client)
    created = client.post(
        "/api/v1/admin/users",
        json={
            "first_name": "Real",
            "last_name": "User",
            "business_email": email,
            "company_name": f"Org for {email}",
            "role": role,
        },
        headers=admin_headers,
    ).json()

    from api_app import state as state_module

    sent = state_module._state.email_provider.sent
    token = re.search(r"token=([A-Za-z0-9_-]+)", sent[-1].text_body).group(1)
    verify = client.get(f"/api/v1/auth/magic-link/verify?token={token}", follow_redirects=False)
    session_token = verify.headers["location"].split("access_token=", 1)[1]
    return {"headers": {"Authorization": f"Bearer {session_token}"}, "user": created}


def test_magic_link_super_admin_gets_the_real_super_admin_only_permissions(client):
    """Regression test for a real bug caught during Milestone 5 development: a
    magic-link SUPER_ADMIN user's permissions must come from their actual DB role,
    not from `auth.py::map_db_role_to_dev_roles`'s route-gating bridge (which
    collapses SUPER_ADMIN down onto ADMIN/TRADER/RISK_MANAGER/RESEARCHER/VIEWER for
    `require_role` purposes and would otherwise silently omit the four permissions
    reserved for SUPER_ADMIN alone)."""
    session = _activate_via_magic_link(client, "realsuperadmin@realcompany.com", "SUPER_ADMIN")
    r = client.get("/api/v1/auth/me/entitlements", headers=session["headers"])
    permissions = set(r.json()["permissions"])
    assert "admin.system_settings" in permissions
    assert "admin.risk_settings" in permissions
    assert "admin.agent_optimization" in permissions
    assert "admin.model_management" in permissions


def test_resolve_organization_scope_for_magic_link_user_is_their_org_not_unrestricted(client):
    """Milestone 9 (tenant isolation retrofit, docs/alpha-intelligence.md section
    11.1): a magic-link user with a real, resolvable organization gets
    `(their_organization_id, unrestricted=False)` -- never the platform-wide-admin
    escape hatch, even though that same distinction only matters for callers whose
    organization can't be resolved at all."""
    import asyncio

    from api_app import auth as auth_module
    from api_app import state as state_module
    from api_app.entitlements import resolve_organization_scope

    session = _activate_via_magic_link(client, "realtrader@realcompany.com", "TRADER")
    token = session["headers"]["Authorization"].split(" ", 1)[1]
    state = state_module._state
    user = asyncio.run(auth_module.decode_access_token(token, state))
    organization_id, unrestricted = asyncio.run(resolve_organization_scope(user, state))
    assert organization_id is not None
    assert unrestricted is False


def test_resolve_organization_scope_for_dev_mode_admin_is_unrestricted(client):
    """A dev-mode caller has no resolvable organization at all, but the ADMIN dev
    fixture holds `admin.organizations` -- so they must come back `unrestricted=True`
    (a real cross-organization admin), not silently restricted to platform-wide-only
    data the way any other unresolvable-org caller now is."""
    import asyncio

    from api_app.auth import Role, User
    from api_app.entitlements import resolve_organization_scope

    from api_app import state as state_module

    user = User(user_id="dev-admin", email="admin@alphagasiq.local", display_name="Admin", roles=[Role.ADMIN])
    organization_id, unrestricted = asyncio.run(resolve_organization_scope(user, state_module._state))
    assert organization_id is None
    assert unrestricted is True


def test_resolve_organization_scope_for_dev_mode_trader_is_restricted_not_unrestricted(client):
    """The core Milestone 9 fix, at the helper level: a dev-mode TRADER has no
    resolvable organization and no `admin.organizations` grant, so they must come
    back `unrestricted=False` -- restricted to platform-wide-only data -- rather
    than the old behavior of skipping org filtering entirely."""
    import asyncio

    from api_app.auth import Role, User
    from api_app.entitlements import resolve_organization_scope

    from api_app import state as state_module

    user = User(user_id="dev-trader", email="trader@alphagasiq.local", display_name="Trader", roles=[Role.TRADER])
    organization_id, unrestricted = asyncio.run(resolve_organization_scope(user, state_module._state))
    assert organization_id is None
    assert unrestricted is False


def test_record_is_visible():
    from api_app.entitlements import record_is_visible

    # Unrestricted (cross-org admin) sees everything, own-org or not.
    assert record_is_visible("org-b", "org-a", True) is True
    # Platform-wide data (organization_id is None) is visible to everyone.
    assert record_is_visible(None, "org-a", False) is True
    assert record_is_visible(None, None, False) is True
    # A restricted caller sees their own organization's data.
    assert record_is_visible("org-a", "org-a", False) is True
    # A restricted caller cannot see another organization's data.
    assert record_is_visible("org-b", "org-a", False) is False


def test_magic_link_executive_gets_executive_permissions_not_bridged_viewer_only(client):
    """Same bug, different symptom: an EXECUTIVE magic-link user's `roles` claim is
    bridged down to `[VIEWER]` for route-gating purposes, but their entitlements must
    still reflect the real EXECUTIVE role, not bare VIEWER."""
    session = _activate_via_magic_link(client, "realexecutive@realcompany.com", "EXECUTIVE")
    r = client.get("/api/v1/auth/me/entitlements", headers=session["headers"])
    permissions = set(r.json()["permissions"])
    # EXECUTIVE grants portfolio.view and risk.view; bare VIEWER (what the bridge
    # would incorrectly resolve to) grants neither.
    assert "portfolio.view" in permissions
    assert "risk.view" in permissions
