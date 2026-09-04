"""Unit tests for `apps/api/api_app/email_service.py`'s template builders — pure
functions, no HTTP/DB involved. `test_magic_link_auth.py` covers these same templates
exercised end-to-end through the real endpoints.
"""

from __future__ import annotations

from api_app.email_service import (
    ConsoleEmailProvider,
    build_account_created_email,
    build_account_status_changed_email,
    build_invitation_resent_email,
    build_magic_link_login_email,
)

_FORBIDDEN_SUBSTRINGS = ("password", "secret", "temporary pin")

_ALL_TEMPLATES = [
    build_account_created_email(
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
        role_name="TRADER",
        magic_link_url="https://api.example.com/verify?token=abc123",
        expires_minutes=15,
    ),
    build_magic_link_login_email(
        email="ada@example.com", magic_link_url="https://api.example.com/verify?token=abc123", expires_minutes=15
    ),
    build_invitation_resent_email(
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
        magic_link_url="https://api.example.com/verify?token=abc123",
        expires_minutes=15,
    ),
    build_account_status_changed_email(first_name="Ada", email="ada@example.com", new_status="SUSPENDED"),
]


def test_no_template_ever_includes_a_password_or_secret():
    for message in _ALL_TEMPLATES:
        lowered = message.text_body.lower()
        for forbidden in _FORBIDDEN_SUBSTRINGS:
            assert forbidden not in lowered, f"{message.subject!r} leaked forbidden content: {forbidden!r}"


def test_account_created_email_includes_magic_link_and_role_and_expiry():
    message = build_account_created_email(
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
        role_name="RESEARCHER",
        magic_link_url="https://api.example.com/verify?token=xyz",
        expires_minutes=15,
    )
    assert message.to == "ada@example.com"
    assert "Account Has Been Created" in message.subject
    assert "https://api.example.com/verify?token=xyz" in message.text_body
    assert "RESEARCHER" in message.text_body
    assert "15" in message.text_body


def test_magic_link_login_email_never_claims_account_was_just_created():
    message = build_magic_link_login_email(
        email="ada@example.com", magic_link_url="https://api.example.com/verify?token=xyz", expires_minutes=15
    )
    assert "created" not in message.text_body.lower()


def test_account_status_changed_email_wording_varies_by_status():
    suspended = build_account_status_changed_email(first_name="Ada", email="ada@example.com", new_status="SUSPENDED")
    reactivated = build_account_status_changed_email(first_name="Ada", email="ada@example.com", new_status="ACTIVE")
    assert "suspended" in suspended.text_body.lower()
    assert "reactivated" in reactivated.text_body.lower()


async def test_console_email_provider_records_but_never_sends():
    provider = ConsoleEmailProvider()
    message = build_magic_link_login_email(
        email="ada@example.com", magic_link_url="https://api.example.com/verify?token=xyz", expires_minutes=15
    )
    await provider.send(message)
    assert provider.sent == [message]
