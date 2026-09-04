"""`EmailProvider` abstraction (docs/access-model.md §3, spec §57) — the platform is
never hardcoded to one email vendor (AWS SES / SendGrid / Resend / Postmark are all
just another `EmailProvider` implementation away). `ConsoleEmailProvider` is the
default in every environment that doesn't set `SMTP_HOST` (this sandbox has no
outbound SMTP access, so it is also what every test runs against);
`SMTPEmailProvider` is a real `smtplib` sender, config-gated exactly like OIDC/
Neo4j/redpanda elsewhere in this codebase.

Every template builder in this module honors the platform's fixed email invariant:
**never include a temporary password, permanent password, authentication secret, or
raw token** — only a single-use magic-link URL.
"""

from __future__ import annotations

import logging
import smtplib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from email.message import EmailMessage as MIMEEmailMessage

from config import branding, get_settings

logger = logging.getLogger(__name__)


@dataclass
class EmailMessage:
    to: str
    subject: str
    text_body: str
    html_body: str | None = None


class EmailProvider(ABC):
    @abstractmethod
    async def send(self, message: EmailMessage) -> None: ...


class ConsoleEmailProvider(EmailProvider):
    """Logs the rendered email instead of sending it. Safe by construction for every
    dev/test/sandbox environment — there is no outbound network call here at all."""

    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.sent.append(message)
        logger.info("EMAIL (console provider, not actually sent) to=%s subject=%r", message.to, message.subject)


class SMTPEmailProvider(EmailProvider):
    """Real `smtplib`-based sender. Active only when `SMTP_HOST` is configured — no
    default dev/test environment sets it, so this class is never exercised by the
    test suite against a live server (mirrors this codebase's existing `NEO4J_URI`/
    `OIDC_ISSUER_URL` config-gated pattern)."""

    def __init__(self, *, host: str, port: int, username: str | None, password: str | None, use_tls: bool) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_tls = use_tls

    async def send(self, message: EmailMessage) -> None:
        settings = get_settings()
        mime_message = MIMEEmailMessage()
        mime_message["Subject"] = message.subject
        mime_message["From"] = settings.email_from_address
        mime_message["To"] = message.to
        mime_message.set_content(message.text_body)
        if message.html_body is not None:
            mime_message.add_alternative(message.html_body, subtype="html")

        with smtplib.SMTP(self._host, self._port) as smtp:
            if self._use_tls:
                smtp.starttls()
            if self._username is not None:
                smtp.login(self._username, self._password or "")
            smtp.send_message(mime_message)


_console_provider_singleton: ConsoleEmailProvider | None = None


def get_email_provider() -> EmailProvider:
    settings = get_settings()
    if settings.smtp_host:
        return SMTPEmailProvider(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            use_tls=settings.smtp_use_tls,
        )
    global _console_provider_singleton
    if _console_provider_singleton is None:
        _console_provider_singleton = ConsoleEmailProvider()
    return _console_provider_singleton


def reset_console_email_provider() -> None:
    """Test-only: gives each test a clean `ConsoleEmailProvider.sent` list."""
    global _console_provider_singleton
    _console_provider_singleton = None


# -- Templates (spec §16, §57) ----------------------------------------------------
#
# Every template below omits a password/secret/raw-token by construction: the only
# credential-shaped value any of them accept is a fully-formed magic-link *URL*.


def build_account_created_email(
    *, first_name: str, last_name: str, email: str, role_name: str, magic_link_url: str, expires_minutes: int
) -> EmailMessage:
    text_body = (
        f"Welcome to {branding.PRODUCT_NAME}.\n\n"
        f"An account has been created for you to access the {branding.PRODUCT_NAME} Agentic "
        "Natural Gas Intelligence & Trading Platform.\n\n"
        f"Name: {first_name} {last_name}\n"
        f"Business Email: {email}\n"
        f"Role: {role_name}\n\n"
        f"Use the secure link below to access your account. This link expires in "
        f"{expires_minutes} minutes and can only be used once:\n"
        f"{magic_link_url}\n\n"
        "If you did not expect this email, or believe it was sent in error, please contact "
        f"{get_settings().support_contact_email} and do not use the link above.\n\n"
        f"{branding.TAGLINE}"
    )
    return EmailMessage(to=email, subject=f"Your {branding.PRODUCT_NAME} Account Has Been Created", text_body=text_body)


def build_magic_link_login_email(*, email: str, magic_link_url: str, expires_minutes: int) -> EmailMessage:
    text_body = (
        f"Use the secure link below to sign in to {branding.PRODUCT_NAME}. This link expires in "
        f"{expires_minutes} minutes and can only be used once:\n"
        f"{magic_link_url}\n\n"
        "If you did not request this sign-in link, you can safely ignore this email — no "
        "action will be taken and your account remains secure.\n\n"
        f"{branding.TAGLINE}"
    )
    return EmailMessage(to=email, subject=f"Your {branding.PRODUCT_NAME} Sign-In Link", text_body=text_body)


def build_invitation_resent_email(
    *, first_name: str, last_name: str, email: str, magic_link_url: str, expires_minutes: int
) -> EmailMessage:
    text_body = (
        f"Hi {first_name},\n\n"
        f"A new secure sign-in link for your {branding.PRODUCT_NAME} account has been issued. "
        "Any previous invitation link you may have received is no longer valid. This new link "
        f"expires in {expires_minutes} minutes and can only be used once:\n"
        f"{magic_link_url}\n\n"
        f"{branding.TAGLINE}"
    )
    return EmailMessage(to=email, subject=f"Your {branding.PRODUCT_NAME} Invitation Has Been Resent", text_body=text_body)


def build_account_status_changed_email(*, first_name: str, email: str, new_status: str) -> EmailMessage:
    """Covers the "Account Suspended" / "Account Reactivated" / "Account Disabled"
    templates from spec §57 — the wording differs only by status, so one builder
    covers all three rather than three near-identical functions."""
    status_copy = {
        "SUSPENDED": "has been temporarily suspended by an administrator",
        "ACTIVE": "has been reactivated",
        "DISABLED": "has been disabled and is unavailable until manually re-enabled",
        "REVOKED": "access has been permanently revoked",
    }.get(new_status, f"status has changed to {new_status}")
    text_body = (
        f"Hi {first_name},\n\n"
        f"Your {branding.PRODUCT_NAME} account {status_copy}. If you have questions, contact "
        f"{get_settings().support_contact_email}.\n\n"
        f"{branding.TAGLINE}"
    )
    return EmailMessage(to=email, subject=f"Your {branding.PRODUCT_NAME} Account Status Has Changed", text_body=text_body)
