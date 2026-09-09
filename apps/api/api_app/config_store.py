"""GUI-managed configuration overlay (super-admin Configuration page).

Values entered in the admin Configuration page are stored in the DB (secrets
Fernet-encrypted with CONFIG_ENCRYPTION_KEY) and overlaid onto ``os.environ`` so
pydantic ``Settings`` (``get_settings``) reads them. ``reload_runtime`` re-applies
the overlay, clears the settings cache, and rebuilds runtime consumers (the data
provider registry) without a container restart.

Some settings are captured deeply at startup (DB engine, JWT signing, event bus,
the LLM client held by every agent) and cannot fully hot-reload — those are
marked ``restart_required`` so the UI can tell the operator to restart the api +
worker containers to fully apply them.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select

from config import get_settings
from db.models import AppConfigRow

_ENC_PREFIX = "fernet:"  # marks a stored value as encrypted


@dataclass
class ConfigItem:
    key: str                       # ENV var name, e.g. "EIA_API_KEY"
    label: str
    group: str
    secret: bool = False
    testable: bool = False
    restart_required: bool = False
    placeholder: str = ""
    kind: str = "text"             # text | bool | number
    help: str = ""


# The settings surfaced in the GUI. Grouped for display. `key` is the env-var
# name pydantic Settings reads (upper-case of the settings attribute).
CATALOG: list[ConfigItem] = [
    # ── AI ──
    ConfigItem("ANTHROPIC_API_KEY", "Anthropic API key", "AI", secret=True, testable=True,
               placeholder="sk-ant-…", help="Enables the real Claude agents (else simulated). Restart to fully apply to running agents.", restart_required=True),
    # ── Data feeds ──
    ConfigItem("EIA_API_KEY", "EIA API key", "Data feeds", secret=True, testable=True,
               placeholder="get free at eia.gov/opendata/register", help="Natural-gas storage/production + ISO/RTO."),
    ConfigItem("NOAA_API_TOKEN", "NOAA API token", "Data feeds", secret=True, placeholder="optional"),
    ConfigItem("NEWS_PROVIDER_API_KEY", "News provider API key", "Data feeds", secret=True, placeholder="optional"),
    ConfigItem("CME_API_ID", "CME API ID", "Data feeds", placeholder="optional (paid feed)"),
    ConfigItem("CME_API_SECRET", "CME API secret", "Data feeds", secret=True, placeholder="optional (paid feed)"),
    ConfigItem("SEC_EDGAR_CONTACT_EMAIL", "SEC EDGAR contact email", "Data feeds", placeholder="you@company.com"),
    ConfigItem("USE_MOCK_MARKET_DATA", "Use mock market data", "Data feeds", kind="bool",
               help="When on, the paid CME/ICE feeds are simulated."),
    ConfigItem("USE_MOCK_NEWS", "Use mock news", "Data feeds", kind="bool"),
    # ── Auth / OIDC ──
    ConfigItem("OIDC_ISSUER_URL", "OIDC issuer URL", "Auth / SSO", testable=True, placeholder="https://issuer.example.com", restart_required=True),
    ConfigItem("OIDC_CLIENT_ID", "OIDC client ID", "Auth / SSO", restart_required=True),
    ConfigItem("OIDC_CLIENT_SECRET", "OIDC client secret", "Auth / SSO", secret=True, restart_required=True),
    ConfigItem("OIDC_REDIRECT_URI", "OIDC redirect URI", "Auth / SSO", restart_required=True),
    ConfigItem("OIDC_AUDIENCE", "OIDC audience", "Auth / SSO", restart_required=True),
    # ── Email / SMTP ──
    ConfigItem("SMTP_HOST", "SMTP host", "Email", placeholder="smtp.example.com", help="Enables magic-link email delivery."),
    ConfigItem("SMTP_PORT", "SMTP port", "Email", kind="number", placeholder="587"),
    ConfigItem("SMTP_USERNAME", "SMTP username", "Email"),
    ConfigItem("SMTP_PASSWORD", "SMTP password", "Email", secret=True),
    ConfigItem("EMAIL_FROM_ADDRESS", "From address", "Email", placeholder="no-reply@alphagasiq.local"),
    # ── Storage / monitoring ──
    ConfigItem("SENTRY_DSN", "Sentry DSN", "Monitoring", secret=True, placeholder="optional", restart_required=True),
    ConfigItem("LOG_LEVEL", "Log level", "Monitoring", placeholder="INFO"),
    # ── Core (restart required) ──
    ConfigItem("DATABASE_URL", "Database URL", "Core (restart to apply)", secret=True, testable=True, restart_required=True,
               placeholder="postgresql+asyncpg://…"),
    ConfigItem("REDIS_URL", "Redis URL", "Core (restart to apply)", testable=True, restart_required=True, placeholder="redis://…"),
    ConfigItem("EVENT_BUS_IMPL", "Event bus", "Core (restart to apply)", restart_required=True, placeholder="memory | redpanda"),
    ConfigItem("API_BASE_URL", "API base URL", "Core (restart to apply)", restart_required=True),
    ConfigItem("CORS_ORIGINS", "CORS origins", "Core (restart to apply)", restart_required=True),
    ConfigItem("ENVIRONMENT", "Environment", "Core (restart to apply)", placeholder="production"),
]

CATALOG_BY_KEY = {c.key: c for c in CATALOG}


def _fernet() -> Fernet | None:
    k = os.environ.get("CONFIG_ENCRYPTION_KEY")
    if not k:
        return None
    try:
        return Fernet(k.encode())
    except Exception:
        return None


def _encrypt(value: str) -> str:
    f = _fernet()
    if f is None:
        return value  # LAN fallback: plaintext (no key configured)
    return _ENC_PREFIX + f.encrypt(value.encode()).decode()


def _decrypt(stored: str) -> str:
    if not stored.startswith(_ENC_PREFIX):
        return stored
    f = _fernet()
    if f is None:
        return ""
    try:
        return f.decrypt(stored[len(_ENC_PREFIX):].encode()).decode()
    except InvalidToken:
        return ""


async def _get_all_raw(session_factory) -> dict[str, str]:
    async with session_factory() as session:
        rows = (await session.execute(select(AppConfigRow))).scalars().all()
        return {r.key: _decrypt(r.value) for r in rows}


async def set_value(session_factory, key: str, value: str) -> None:
    """Upsert one config value (encrypted at rest)."""
    stored = _encrypt(value)
    async with session_factory() as session:
        row = await session.get(AppConfigRow, key)
        if row is None:
            session.add(AppConfigRow(key=key, value=stored))
        else:
            row.value = stored
        await session.commit()


async def delete_value(session_factory, key: str) -> None:
    async with session_factory() as session:
        row = await session.get(AppConfigRow, key)
        if row is not None:
            await session.delete(row)
            await session.commit()


async def apply_overlay(session_factory) -> list[str]:
    """DB config → os.environ → clear the Settings cache. Returns keys applied."""
    vals = await _get_all_raw(session_factory)
    applied = []
    for k, v in vals.items():
        if v != "":
            os.environ[k] = v
            applied.append(k)
    get_settings.cache_clear()
    return applied


async def reload_runtime(state) -> dict:
    """Re-apply overlay + rebuild hot-reloadable consumers (data provider registry).
    Returns {applied: [...], restart_required: [...]}."""
    applied = await apply_overlay(state.repo.session_factory)
    try:
        from data_service.registry import build_default_registry
        state.providers = build_default_registry()
    except Exception:
        pass
    restart = [k for k in applied if CATALOG_BY_KEY.get(k) and CATALOG_BY_KEY[k].restart_required]
    return {"applied": applied, "restart_required": restart}


async def masked_view(session_factory) -> list[dict]:
    """The catalog + current values, secrets masked, for the GUI."""
    vals = await _get_all_raw(session_factory)
    out = []
    for c in CATALOG:
        # Effective current value = DB overlay, else the live env/settings value.
        current = vals.get(c.key)
        env_val = os.environ.get(c.key)
        has_value = bool(current) or bool(env_val)
        if c.secret:
            display = "" if not has_value else "••••••••"
        else:
            display = current if current is not None else (env_val or "")
        out.append({
            "key": c.key, "label": c.label, "group": c.group, "secret": c.secret,
            "testable": c.testable, "restart_required": c.restart_required,
            "placeholder": c.placeholder, "kind": c.kind, "help": c.help,
            "has_value": has_value, "display": display,
        })
    return out


async def test_value(key: str, value: str) -> tuple[bool, str]:
    """Probe a credential/URL. `value` is the candidate (test-before-save)."""
    import httpx
    v = (value or "").strip()
    if not v:
        return False, "No value to test."
    try:
        if key == "EIA_API_KEY":
            async with httpx.AsyncClient(timeout=12) as c:
                r = await c.get("https://api.eia.gov/v2/natural-gas/stor/wkly/data/",
                                params={"api_key": v, "length": 1})
            return (r.status_code == 200, "EIA key valid." if r.status_code == 200 else f"EIA returned HTTP {r.status_code}.")
        if key == "ANTHROPIC_API_KEY":
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=v)
            await client.models.list()
            return True, "Anthropic key valid."
        if key == "OIDC_ISSUER_URL":
            url = v.rstrip("/") + "/.well-known/openid-configuration"
            async with httpx.AsyncClient(timeout=12) as c:
                r = await c.get(url)
            return (r.status_code == 200, "OIDC issuer reachable." if r.status_code == 200 else f"Issuer returned HTTP {r.status_code}.")
        if key == "DATABASE_URL":
            from sqlalchemy.ext.asyncio import create_async_engine
            from sqlalchemy import text
            eng = create_async_engine(v)
            try:
                async with eng.connect() as conn:
                    await conn.execute(text("SELECT 1"))
                return True, "Database connection OK."
            finally:
                await eng.dispose()
        if key == "REDIS_URL":
            try:
                import redis.asyncio as aioredis
            except ImportError:
                return False, "redis client not installed in the image."
            r = aioredis.from_url(v)
            try:
                await r.ping()
                return True, "Redis connection OK."
            finally:
                await r.aclose()
        return False, "No test available for this setting."
    except Exception as e:  # noqa: BLE001 - surface the probe error to the operator
        return False, f"{type(e).__name__}: {str(e)[:160]}"
