"""Milestone 3: real magic-link authentication, sessions, and the email service that
backs them (docs/access-model.md §§3-4, spec §§16-21). `ConsoleEmailProvider` (the
default in every test/dev environment — see `apps/api/api_app/email_service.py`)
never actually sends anything; it only records what would have been sent, which is
exactly what these tests inspect to recover the magic-link token a real user would
get by clicking a link in their inbox.
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


def _sent_emails():
    from api_app import state as state_module

    return state_module._state.email_provider.sent


def _extract_token(text_body: str) -> str:
    match = re.search(r"token=([A-Za-z0-9_-]+)", text_body)
    assert match, f"no magic-link token found in email body: {text_body!r}"
    return match.group(1)


def _create_invited_user(client, *, email: str, role: str = "TRADER") -> dict:
    headers = _admin_headers(client)
    r = client.post(
        "/api/v1/admin/users",
        json={
            "first_name": "Pat",
            "last_name": "Nguyen",
            "business_email": email,
            "company_name": f"Org for {email}",
            "role": role,
        },
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()


def test_create_user_sends_invitation_email_with_magic_link_and_no_secret(client):
    before = len(_sent_emails())
    user = _create_invited_user(client, email="newhire@realcompany.com")
    sent = _sent_emails()
    assert len(sent) == before + 1

    message = sent[-1]
    assert message.to == "newhire@realcompany.com"
    assert "Account Has Been Created" in message.subject
    assert "/auth/magic-link/verify?token=" in message.text_body
    assert user["first_name"] in message.text_body
    assert user["role_name"] == "TRADER"

    # The fixed "never include a password/secret" invariant (spec §16), checked
    # literally against the rendered text, not just by code inspection.
    lowered = message.text_body.lower()
    for forbidden in ("password", "secret"):
        assert forbidden not in lowered


def test_magic_link_verify_activates_invited_user_and_issues_working_session(client):
    user = _create_invited_user(client, email="activate.me@realcompany.com")
    token = _extract_token(_sent_emails()[-1].text_body)

    verify = client.get(f"/api/v1/auth/magic-link/verify?token={token}", follow_redirects=False)
    assert verify.status_code in (302, 307)
    location = verify.headers["location"]
    assert location.startswith("http://localhost:3000/platform#access_token=")
    session_token = location.split("access_token=", 1)[1]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {session_token}"})
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "activate.me@realcompany.com"
    assert body["session_id"] is not None
    assert "TRADER" in body["roles"]

    fetched = client.get(f"/api/v1/admin/users/{user['id']}", headers=_admin_headers(client))
    assert fetched.json()["status"] == "ACTIVE"
    assert fetched.json()["activated_at"] is not None


def test_magic_link_token_is_single_use(client):
    _create_invited_user(client, email="onceonly@realcompany.com")
    token = _extract_token(_sent_emails()[-1].text_body)

    first = client.get(f"/api/v1/auth/magic-link/verify?token={token}", follow_redirects=False)
    assert first.status_code in (302, 307)

    second = client.get(f"/api/v1/auth/magic-link/verify?token={token}", follow_redirects=False)
    assert second.status_code == 401


def test_magic_link_verify_rejects_unknown_token(client):
    r = client.get("/api/v1/auth/magic-link/verify?token=not-a-real-token", follow_redirects=False)
    assert r.status_code == 401


async def test_magic_link_verify_rejects_expired_token(client):
    from datetime import datetime, timedelta, timezone

    from api_app import magic_link as magic_link_module
    from api_app import state as state_module

    user = _create_invited_user(client, email="expired@realcompany.com")
    state = state_module._state
    raw_token = "deliberately-expired-test-token"
    await state.repo.create_magic_link_token(
        user_id=user["id"],
        token_hash=magic_link_module.hash_token(raw_token),
        purpose="LOGIN",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    r = client.get(f"/api/v1/auth/magic-link/verify?token={raw_token}", follow_redirects=False)
    assert r.status_code == 401


def test_magic_link_request_for_active_user_sends_login_email(client):
    _create_invited_user(client, email="willactivate@realcompany.com")
    token = _extract_token(_sent_emails()[-1].text_body)
    client.get(f"/api/v1/auth/magic-link/verify?token={token}", follow_redirects=False)

    before = len(_sent_emails())
    r = client.post("/api/v1/auth/magic-link/request", json={"email": "willactivate@realcompany.com"})
    assert r.status_code == 200
    assert r.json() == {
        "detail": "If an authorized AlphaGasIQ account exists for this email, a secure sign-in link has been sent."
    }
    sent = _sent_emails()
    assert len(sent) == before + 1
    assert "Sign-In Link" in sent[-1].subject


def test_magic_link_request_for_unknown_email_sends_nothing_but_same_response(client):
    before = len(_sent_emails())
    r = client.post("/api/v1/auth/magic-link/request", json={"email": "nobody-real@example.com"})
    assert r.status_code == 200
    assert r.json() == {
        "detail": "If an authorized AlphaGasIQ account exists for this email, a secure sign-in link has been sent."
    }
    assert len(_sent_emails()) == before


def test_magic_link_request_for_suspended_user_sends_nothing(client):
    user = _create_invited_user(client, email="gettingsuspended@realcompany.com")
    token = _extract_token(_sent_emails()[-1].text_body)
    client.get(f"/api/v1/auth/magic-link/verify?token={token}", follow_redirects=False)

    headers = _admin_headers(client)
    client.post(f"/api/v1/admin/users/{user['id']}/status", json={"status": "SUSPENDED"}, headers=headers)

    before = len(_sent_emails())
    r = client.post("/api/v1/auth/magic-link/request", json={"email": "gettingsuspended@realcompany.com"})
    assert r.status_code == 200
    assert len(_sent_emails()) == before


def test_magic_link_request_is_rate_limited(client):
    _create_invited_user(client, email="ratelimited@realcompany.com")
    # First request already happened at creation time (the invitation); exhaust the
    # rest of the default 5-request budget for this email.
    for _ in range(6):
        r = client.post("/api/v1/auth/magic-link/request", json={"email": "ratelimited@realcompany.com"})
        assert r.status_code == 200  # always the same generic response, even when limited

    sent_count = sum(1 for m in _sent_emails() if m.to == "ratelimited@realcompany.com")
    # 1 invitation email + at most 5 more (the rate limit budget) — never 7.
    assert sent_count <= 6


def test_resend_invitation_invalidates_prior_link_and_only_works_while_invited(client):
    user = _create_invited_user(client, email="resend.me@realcompany.com")
    old_token = _extract_token(_sent_emails()[-1].text_body)
    headers = _admin_headers(client)

    r = client.post(f"/api/v1/admin/users/{user['id']}/resend-invitation", headers=headers)
    assert r.status_code == 200
    new_token = _extract_token(_sent_emails()[-1].text_body)
    assert new_token != old_token

    old_attempt = client.get(f"/api/v1/auth/magic-link/verify?token={old_token}", follow_redirects=False)
    assert old_attempt.status_code == 401

    new_attempt = client.get(f"/api/v1/auth/magic-link/verify?token={new_token}", follow_redirects=False)
    assert new_attempt.status_code in (302, 307)

    # Now ACTIVE -- resend-invitation no longer applies.
    again = client.post(f"/api/v1/admin/users/{user['id']}/resend-invitation", headers=headers)
    assert again.status_code == 400


def test_resend_invitation_requires_admin(client):
    user = _create_invited_user(client, email="noaccess@realcompany.com")
    trader_login = client.post(
        "/api/v1/auth/login", json={"email": "trader@alphagasiq.local", "password": "trader-dev-password"}
    )
    trader_headers = {"Authorization": f"Bearer {trader_login.json()['access_token']}"}
    r = client.post(f"/api/v1/admin/users/{user['id']}/resend-invitation", headers=trader_headers)
    assert r.status_code == 403


def test_logout_revokes_session_and_token_stops_working(client):
    _create_invited_user(client, email="logmeout@realcompany.com")
    token = _extract_token(_sent_emails()[-1].text_body)
    verify = client.get(f"/api/v1/auth/magic-link/verify?token={token}", follow_redirects=False)
    session_token = verify.headers["location"].split("access_token=", 1)[1]
    session_headers = {"Authorization": f"Bearer {session_token}"}

    before_logout = client.get("/api/v1/auth/me", headers=session_headers)
    assert before_logout.status_code == 200

    logout = client.post("/api/v1/auth/logout", headers=session_headers)
    assert logout.status_code == 200

    after_logout = client.get("/api/v1/auth/me", headers=session_headers)
    assert after_logout.status_code == 401


def test_dev_mode_login_is_unaffected_by_session_revocation_logic(client):
    """Regression test: dev-mode tokens carry no `sid` claim, so `POST /auth/logout`
    and the session-revocation check in `decode_access_token` must be complete
    no-ops for them -- this is the "existing functionality preserved" guarantee for
    every other test in this suite that still logs in via `/auth/login`."""
    headers = _admin_headers(client)
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["session_id"] is None

    logout = client.post("/api/v1/auth/logout", headers=headers)
    assert logout.status_code == 200

    still_works = client.get("/api/v1/auth/me", headers=headers)
    assert still_works.status_code == 200


def test_admin_can_list_and_revoke_a_users_sessions(client):
    user = _create_invited_user(client, email="watchme@realcompany.com")
    token = _extract_token(_sent_emails()[-1].text_body)
    verify = client.get(f"/api/v1/auth/magic-link/verify?token={token}", follow_redirects=False)
    session_token = verify.headers["location"].split("access_token=", 1)[1]

    admin_headers = _admin_headers(client)
    sessions = client.get(f"/api/v1/admin/users/{user['id']}/sessions", headers=admin_headers)
    assert sessions.status_code == 200
    assert len(sessions.json()) == 1
    session_id = sessions.json()[0]["id"]

    revoke = client.post(f"/api/v1/admin/users/{user['id']}/sessions/{session_id}/revoke", headers=admin_headers)
    assert revoke.status_code == 200
    assert revoke.json()["revoked_at"] is not None

    rejected = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {session_token}"})
    assert rejected.status_code == 401


def test_status_change_sends_notification_email(client):
    user = _create_invited_user(client, email="willbesuspended@realcompany.com")
    token = _extract_token(_sent_emails()[-1].text_body)
    client.get(f"/api/v1/auth/magic-link/verify?token={token}", follow_redirects=False)

    headers = _admin_headers(client)
    before = len(_sent_emails())
    r = client.post(f"/api/v1/admin/users/{user['id']}/status", json={"status": "SUSPENDED"}, headers=headers)
    assert r.status_code == 200
    sent = _sent_emails()
    assert len(sent) == before + 1
    assert "suspended" in sent[-1].text_body.lower()
