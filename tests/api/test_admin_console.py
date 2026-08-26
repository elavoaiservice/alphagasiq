"""Milestone 6: admin overview metrics, feature management, system settings, and the
user/organization profile-edit endpoints that round out spec §§30-38.
"""

from __future__ import annotations

import re

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


def _create_user(client, *, email: str, role: str = "TRADER", company_name: str | None = None) -> dict:
    headers = _admin_headers(client)
    r = client.post(
        "/api/v1/admin/users",
        json={
            "first_name": "Pat",
            "last_name": "Nguyen",
            "business_email": email,
            "company_name": company_name or f"Org for {email}",
            "role": role,
        },
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()


def _extract_latest_token(client, email: str) -> str:
    from api_app import state as state_module

    sent = state_module._state.email_provider.sent
    message = next(m for m in reversed(sent) if m.to == email)
    return re.search(r"token=([A-Za-z0-9_-]+)", message.text_body).group(1)


def _activate(client, email: str) -> None:
    token = _extract_latest_token(client, email)
    r = client.get(f"/api/v1/auth/magic-link/verify?token={token}", follow_redirects=False)
    assert r.status_code in (302, 307)


def _login_as(client, email: str) -> dict:
    """Requests and consumes a fresh magic link, returning bearer-auth headers for a
    real (already-`ACTIVE`) DB user -- needed to test SUPER_ADMIN-only endpoints,
    since `_admin_headers`'s dev-mode ADMIN fixture is a different, lesser role."""
    r = client.post("/api/v1/auth/magic-link/request", json={"email": email})
    assert r.status_code == 200
    token = _extract_latest_token(client, email)
    verify = client.get(f"/api/v1/auth/magic-link/verify?token={token}", follow_redirects=False)
    session_token = verify.headers["location"].split("access_token=", 1)[1]
    return {"Authorization": f"Bearer {session_token}"}


# -- overview -------------------------------------------------------------------------


def test_admin_overview_reports_user_and_org_counts(client):
    _create_user(client, email="overview.invited@realcompany.com")
    active_user = _create_user(client, email="overview.active@realcompany.com")
    _activate(client, active_user["email"])

    r = client.get("/api/v1/admin/overview", headers=_admin_headers(client))
    assert r.status_code == 200
    body = r.json()
    assert body["active_users"] >= 1
    assert body["invited_users"] >= 1
    assert body["active_organizations"] >= 1
    assert "not_yet_available" in body
    assert "model_health" in body["not_yet_available"]
    assert body["data_feed_health"]["total_feeds"] >= 1


def test_admin_overview_requires_admin_dashboard_permission(client):
    r = client.get("/api/v1/admin/overview", headers=_trader_headers(client))
    assert r.status_code == 403


def test_admin_overview_requires_auth(client):
    r = client.get("/api/v1/admin/overview")
    assert r.status_code == 401


# -- feature management -----------------------------------------------------------


def test_list_features_returns_the_full_catalog(client):
    r = client.get("/api/v1/admin/features", headers=_admin_headers(client))
    assert r.status_code == 200
    keys = {f["key"] for f in r.json()}
    assert "paper_trading" in keys
    assert len(keys) == 18


def test_toggle_feature_globally(client):
    headers = _admin_headers(client)
    off = client.put("/api/v1/admin/features/experimental_features", json={"enabled": False}, headers=headers)
    assert off.status_code == 200
    assert off.json()["globally_enabled"] is False

    features = client.get("/api/v1/admin/features", headers=headers).json()
    assert next(f for f in features if f["key"] == "experimental_features")["globally_enabled"] is False


def test_toggle_unknown_feature_is_404(client):
    r = client.put(
        "/api/v1/admin/features/not_a_real_feature", json={"enabled": False}, headers=_admin_headers(client)
    )
    assert r.status_code == 404


def test_role_feature_grant_can_be_toggled(client):
    headers = _admin_headers(client)
    before = client.get("/api/v1/admin/roles/VIEWER/features", headers=headers).json()
    assert before["features"]["paper_trading"] is False

    r = client.put("/api/v1/admin/roles/VIEWER/features/paper_trading", json={"enabled": True}, headers=headers)
    assert r.status_code == 200
    assert r.json()["enabled"] is True

    after = client.get("/api/v1/admin/roles/VIEWER/features", headers=headers).json()
    assert after["features"]["paper_trading"] is True


def test_organization_feature_override_restricts_below_role(client):
    headers = _admin_headers(client)
    user = _create_user(client, email="orgoverride@realcompany.com", role="TRADER", company_name="Override Co")
    _activate(client, user["email"])

    r = client.put(
        f"/api/v1/admin/organizations/{user['organization_id']}/features/paper_trading",
        json={"enabled": False},
        headers=headers,
    )
    assert r.status_code == 200

    entitlements = client.get(f"/api/v1/admin/users/{user['id']}/entitlements", headers=headers).json()
    assert entitlements["features"]["paper_trading"] is False


def test_user_feature_override_cannot_exceed_role_for_security_sensitive_feature(client):
    """spec §24 "deny-overrides for security-sensitive features" -- an enabled=True
    user override can't grant a sensitive feature the role doesn't already allow."""
    headers = _admin_headers(client)
    user = _create_user(client, email="usercantexceed@realcompany.com", role="VIEWER")
    _activate(client, user["email"])

    r = client.put(
        f"/api/v1/admin/users/{user['id']}/features/risk_analytics", json={"enabled": True}, headers=headers
    )
    assert r.status_code == 200

    entitlements = client.get(f"/api/v1/admin/users/{user['id']}/entitlements", headers=headers).json()
    # VIEWER's role doesn't grant risk_analytics, so the override can't manufacture it.
    assert entitlements["features"]["risk_analytics"] is False


def test_feature_management_requires_permission(client):
    r = client.get("/api/v1/admin/features", headers=_trader_headers(client))
    assert r.status_code == 403


# -- system settings ---------------------------------------------------------------


def test_list_settings_returns_seeded_defaults(client):
    user = _create_user(client, email="settingsreader@realcompany.com", role="SUPER_ADMIN")
    _activate(client, user["email"])
    headers = _login_as(client, user["email"])

    r = client.get("/api/v1/admin/settings", headers=headers)
    assert r.status_code == 200
    keys = {s["key"] for s in r.json()}
    assert "platform_name" in keys
    assert "support_email" in keys


def test_admin_role_cannot_list_system_settings(client):
    """Same SUPER_ADMIN-only boundary as the write endpoint, checked on the read
    side too."""
    r = client.get("/api/v1/admin/settings", headers=_admin_headers(client))
    assert r.status_code == 403


def test_admin_role_cannot_edit_system_settings_only_super_admin_can(client):
    """admin.system_settings is reserved for SUPER_ADMIN (docs/access-model.md §5) --
    the dev-mode ADMIN fixture maps to the DB ADMIN role, which does not have it."""
    r = client.put(
        "/api/v1/admin/settings/platform_name", json={"value": "New Name"}, headers=_admin_headers(client)
    )
    assert r.status_code == 403


def test_update_setting_versions_and_records_history(client):
    user = _create_user(client, email="superadmin.settings@realcompany.com", role="SUPER_ADMIN")
    _activate(client, user["email"])
    super_admin_headers = _login_as(client, user["email"])

    before = client.get("/api/v1/admin/settings/platform_name", headers=super_admin_headers).json()
    assert before["version"] == 1

    updated = client.put(
        "/api/v1/admin/settings/platform_name", json={"value": "AlphaGasIQ Pro"}, headers=super_admin_headers
    )
    assert updated.status_code == 200
    assert updated.json()["value"] == "AlphaGasIQ Pro"
    assert updated.json()["version"] == 2

    history = client.get("/api/v1/admin/settings/platform_name/history", headers=super_admin_headers).json()
    assert len(history) == 1
    assert history[0]["value"] == "AlphaGasIQ"
    assert history[0]["version"] == 1


def test_update_unknown_setting_is_404(client):
    user = _create_user(client, email="unknownsetting@realcompany.com", role="SUPER_ADMIN")
    _activate(client, user["email"])
    headers = _login_as(client, user["email"])

    r = client.put("/api/v1/admin/settings/not_a_real_setting", json={"value": "x"}, headers=headers)
    assert r.status_code == 404


# -- user profile edits -------------------------------------------------------------


def test_patch_user_profile_updates_only_provided_fields(client):
    headers = _admin_headers(client)
    user = _create_user(client, email="editme@realcompany.com", role="TRADER")

    r = client.patch(f"/api/v1/admin/users/{user['id']}", json={"job_title": "Head Trader"}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["job_title"] == "Head Trader"
    assert body["first_name"] == "Pat"  # untouched


def test_patch_user_profile_can_reassign_role_and_organization(client):
    headers = _admin_headers(client)
    user = _create_user(client, email="reassign@realcompany.com", role="VIEWER")

    r = client.patch(
        f"/api/v1/admin/users/{user['id']}",
        json={"role": "RESEARCHER", "company_name": "New Employer Inc"},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["role_name"] == "RESEARCHER"
    assert r.json()["organization_name"] == "New Employer Inc"


def test_patch_user_profile_rejects_unknown_role(client):
    headers = _admin_headers(client)
    user = _create_user(client, email="badrole2@realcompany.com")
    r = client.patch(f"/api/v1/admin/users/{user['id']}", json={"role": "NOT_REAL"}, headers=headers)
    assert r.status_code == 400


def test_send_login_link_requires_active_status(client):
    headers = _admin_headers(client)
    user = _create_user(client, email="stillinvited@realcompany.com")
    r = client.post(f"/api/v1/admin/users/{user['id']}/send-login-link", headers=headers)
    assert r.status_code == 400

    _activate(client, user["email"])
    before = len(client.get("/api/v1/admin/users", headers=headers).json())
    r2 = client.post(f"/api/v1/admin/users/{user['id']}/send-login-link", headers=headers)
    assert r2.status_code == 200
    assert before == len(client.get("/api/v1/admin/users", headers=headers).json())  # no new user created


def test_patch_organization_updates_data_entitlements(client):
    headers = _admin_headers(client)
    org = client.post("/api/v1/admin/organizations", json={"name": "Entitlement Test Co"}, headers=headers).json()

    r = client.patch(
        f"/api/v1/admin/organizations/{org['id']}",
        json={"data_entitlements": {"eia_full_history": True}},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["data_entitlements"] == {"eia_full_history": True}
