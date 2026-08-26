from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from schemas import (
    InvestmentCommitteeDecision,
    PostTradeAnalysis,
    PriceForecast,
    RiskCheckResult,
    RiskLimits,
    TradeIdea,
)

from .engine import build_engine, build_sessionmaker
from .models import (
    ApprovalRow,
    Base,
    ChatConversationRow,
    ChatMessageRow,
    CommitteeDecisionRow,
    ContactInquiryRow,
    DataFeedConfigRow,
    DataFeedEventRow,
    DecisionJournalRow,
    FeatureRow,
    MagicLinkTokenRow,
    OrganizationFeatureEntitlementRow,
    OrganizationRow,
    PermissionRow,
    PostTradeAnalysisRow,
    RiskCheckRow,
    RiskLimitsRow,
    RoleFeatureEntitlementRow,
    RolePermissionRow,
    RoleRow,
    SessionRow,
    SystemSettingHistoryRow,
    SystemSettingRow,
    TradeIdeaRow,
    UserFeatureOverrideRow,
    UserRow,
)

# The 8 fixed roles from docs/access-model.md §5 (spec §23). Roles are DB rows (not a
# hardcoded enum) so custom roles remain structurally possible, but only these 8 are
# ever seeded.
_ROLE_NAMES = [
    "SUPER_ADMIN",
    "ADMIN",
    "TRADER",
    "RISK_MANAGER",
    "RESEARCHER",
    "EXECUTIVE",
    "VIEWER",
    "API_USER",
]

# The full permission-key list from docs/access-model.md §5 (spec §23), verbatim.
_PERMISSION_KEYS = [
    "dashboard.view",
    "market_data.view",
    "weather.view",
    "storage.view",
    "pipeline.view",
    "lng.view",
    "power.view",
    "news.view",
    "trading_recommendations.view",
    "trading_recommendations.challenge",
    "chief_agent.chat",
    "portfolio.view",
    "portfolio.manage",
    "risk.view",
    "risk.manage",
    "paper_trading.view",
    "paper_trading.execute",
    "data_export",
    "api_access",
    "admin.dashboard",
    "admin.users.view",
    "admin.users.create",
    "admin.users.edit",
    "admin.users.suspend",
    "admin.users.revoke",
    "admin.users.permissions",
    "admin.users.features",
    "admin.users.sessions",
    "admin.organizations",
    "admin.data_feeds",
    "admin.system_settings",
    "admin.agent_management",
    "admin.agent_optimization",
    "admin.model_management",
    "admin.audit_logs",
    "admin.feature_management",
    "admin.risk_settings",
]

# Permissions reserved for SUPER_ADMIN: the system-level/risk/model/agent-optimization
# controls the spec keeps behind the strictest boundary (docs/risk-framework.md — the
# Risk Governor and agent-optimization approval chain are never reachable by a lesser
# role). ADMIN gets every other permission, including day-to-day user/org/feature/
# data-feed/agent administration.
_SUPER_ADMIN_ONLY_PERMISSIONS = {
    "admin.system_settings",
    "admin.risk_settings",
    "admin.agent_optimization",
    "admin.model_management",
}

# Default role -> permission grants seeded at startup. This is the initial, reviewable
# default (docs/access-model.md §5); full entitlement enforcement (require_permission
# dependencies, Feature/*Entitlement tables) lands in Milestone 4, at which point this
# mapping becomes admin-editable rather than a fixed seed.
_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "SUPER_ADMIN": list(_PERMISSION_KEYS),
    "ADMIN": [p for p in _PERMISSION_KEYS if p not in _SUPER_ADMIN_ONLY_PERMISSIONS],
    "TRADER": [
        "dashboard.view",
        "market_data.view",
        "weather.view",
        "storage.view",
        "pipeline.view",
        "lng.view",
        "power.view",
        "news.view",
        "trading_recommendations.view",
        "trading_recommendations.challenge",
        "chief_agent.chat",
        "portfolio.view",
        "portfolio.manage",
        "paper_trading.view",
        "paper_trading.execute",
    ],
    "RISK_MANAGER": [
        "dashboard.view",
        "market_data.view",
        "weather.view",
        "storage.view",
        "pipeline.view",
        "lng.view",
        "power.view",
        "news.view",
        "trading_recommendations.view",
        "chief_agent.chat",
        "portfolio.view",
        "risk.view",
        "risk.manage",
        "paper_trading.view",
    ],
    "RESEARCHER": [
        "dashboard.view",
        "market_data.view",
        "weather.view",
        "storage.view",
        "pipeline.view",
        "lng.view",
        "power.view",
        "news.view",
        "trading_recommendations.view",
        "trading_recommendations.challenge",
        "chief_agent.chat",
        "portfolio.view",
        "risk.view",
        "data_export",
    ],
    "EXECUTIVE": [
        "dashboard.view",
        "market_data.view",
        "weather.view",
        "storage.view",
        "pipeline.view",
        "lng.view",
        "power.view",
        "news.view",
        "trading_recommendations.view",
        "portfolio.view",
        "risk.view",
        "chief_agent.chat",
    ],
    "VIEWER": [
        "dashboard.view",
        "market_data.view",
        "weather.view",
        "storage.view",
        "pipeline.view",
        "lng.view",
        "power.view",
        "news.view",
        "trading_recommendations.view",
    ],
    "API_USER": [
        "market_data.view",
        "weather.view",
        "storage.view",
        "pipeline.view",
        "lng.view",
        "power.view",
        "news.view",
        "data_export",
        "api_access",
    ],
}

# Feature catalog from docs/access-model.md §5 (spec §24), verbatim. Each entry is
# (key, display name, security_sensitive) — a `security_sensitive` feature gets
# deny-only user-level overrides (see `apps/api/api_app/entitlements.py`).
_FEATURES: list[tuple[str, str, bool]] = [
    ("market_dashboard", "Market Dashboard", False),
    ("ng_fundamentals", "Natural Gas Fundamentals", False),
    ("weather_intelligence", "Weather Intelligence", False),
    ("storage_forecast", "Storage Forecast", False),
    ("pipeline_intelligence", "Pipeline Intelligence", False),
    ("lng_intelligence", "LNG Intelligence", False),
    ("power_market_intelligence", "Power Market Intelligence", False),
    ("news_intelligence", "News Intelligence", False),
    ("ai_trade_recommendations", "AI Trade Recommendations", False),
    ("chief_trading_agent_chat", "Chief Trading Agent Chat", True),
    ("portfolio_analytics", "Portfolio Analytics", True),
    ("risk_analytics", "Risk Analytics", True),
    ("ng_digital_twin", "Natural Gas Digital Twin", False),
    ("historical_research", "Historical Research", False),
    ("data_export", "Data Export", True),
    ("api_access", "API Access", True),
    ("paper_trading", "Paper Trading", True),
    ("experimental_features", "Experimental Features", True),
]

# Default role -> feature grants, mirroring _ROLE_PERMISSIONS' capability shape.
# Role-level feature access is deny-by-default: a role only has a feature if it's
# listed here (see `RoleFeatureEntitlementRow`'s docstring).
_ROLE_FEATURES: dict[str, list[str]] = {
    "SUPER_ADMIN": [key for key, _, _ in _FEATURES],
    "ADMIN": [key for key, _, _ in _FEATURES],
    "TRADER": [
        "market_dashboard",
        "ng_fundamentals",
        "weather_intelligence",
        "storage_forecast",
        "pipeline_intelligence",
        "lng_intelligence",
        "power_market_intelligence",
        "news_intelligence",
        "ai_trade_recommendations",
        "chief_trading_agent_chat",
        "portfolio_analytics",
        "ng_digital_twin",
        "paper_trading",
    ],
    "RISK_MANAGER": [
        "market_dashboard",
        "ng_fundamentals",
        "weather_intelligence",
        "storage_forecast",
        "pipeline_intelligence",
        "lng_intelligence",
        "power_market_intelligence",
        "news_intelligence",
        "ai_trade_recommendations",
        "chief_trading_agent_chat",
        "portfolio_analytics",
        "risk_analytics",
        "ng_digital_twin",
    ],
    "RESEARCHER": [
        "market_dashboard",
        "ng_fundamentals",
        "weather_intelligence",
        "storage_forecast",
        "pipeline_intelligence",
        "lng_intelligence",
        "power_market_intelligence",
        "news_intelligence",
        "ai_trade_recommendations",
        "chief_trading_agent_chat",
        "ng_digital_twin",
        "historical_research",
        "data_export",
    ],
    "EXECUTIVE": [
        "market_dashboard",
        "ng_fundamentals",
        "weather_intelligence",
        "storage_forecast",
        "pipeline_intelligence",
        "lng_intelligence",
        "power_market_intelligence",
        "news_intelligence",
        "ai_trade_recommendations",
        "chief_trading_agent_chat",
        "portfolio_analytics",
        "risk_analytics",
        "ng_digital_twin",
    ],
    "VIEWER": [
        "market_dashboard",
        "ng_fundamentals",
        "weather_intelligence",
        "storage_forecast",
        "pipeline_intelligence",
        "lng_intelligence",
        "power_market_intelligence",
        "news_intelligence",
        "ng_digital_twin",
    ],
    "API_USER": [
        "market_dashboard",
        "ng_fundamentals",
        "weather_intelligence",
        "storage_forecast",
        "pipeline_intelligence",
        "lng_intelligence",
        "power_market_intelligence",
        "news_intelligence",
        "data_export",
        "api_access",
    ],
}


# System settings catalog (spec §38), seeded once at first boot. Each value is
# already JSON-shaped (a plain string for most, a dict for the handful of
# structured ones) since `SystemSettingRow.value` is a JSON column.
_SYSTEM_SETTINGS_DEFAULTS: dict[str, object] = {
    "platform_name": "AlphaGasIQ",
    "platform_description": "Agentic natural gas intelligence & paper-trading platform.",
    "market_coverage": "North America",
    "supported_commodities": ["Henry Hub Natural Gas"],
    "system_status_message": "",
    "maintenance_message": "",
    "support_email": "support@alphagasiq.local",
    "contact_information": "",
    "legal_disclaimer": "AlphaGasIQ is a decision-support platform. Nothing herein is investment advice.",
    "trading_disclaimer": "All trading on this platform is simulated (paper trading only).",
    "default_timezone": "America/New_York",
    "default_currency": "USD",
    "default_units": "Bcf/d",
    "default_market": "HENRY_HUB",
    "default_dashboard": "market",
    "data_freshness_policies": {},
    "alert_thresholds": {},
    "notification_settings": {},
    "feature_defaults": {},
    "chat_defaults": {},
}


def _organization_to_dict(row: OrganizationRow) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "website": row.website,
        "industry": row.industry,
        "company_type": row.company_type,
        "country": row.country,
        "state_region": row.state_region,
        "status": row.status,
        "billing_plan": row.billing_plan,
        "account_owner": row.account_owner,
        "primary_contact": row.primary_contact,
        "feature_package": row.feature_package,
        "data_entitlements": row.data_entitlements,
        "notes": row.notes,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _role_to_dict(row: RoleRow) -> dict:
    return {"id": row.id, "name": row.name, "description": row.description}


def _data_feed_config_to_dict(row: DataFeedConfigRow) -> dict:
    return {
        "provider_id": row.provider_id,
        "enabled": row.enabled,
        "paused": row.paused,
        "polling_frequency_seconds": row.polling_frequency_seconds,
        "freshness_threshold_seconds": row.freshness_threshold_seconds,
        "priority": row.priority,
        "fallback_provider_id": row.fallback_provider_id,
        "notes": row.notes,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at,
    }


def _data_feed_event_to_dict(row: DataFeedEventRow) -> dict:
    return {
        "id": row.id,
        "provider_id": row.provider_id,
        "event_type": row.event_type,
        "status": row.status,
        "detail": row.detail,
        "records_received": row.records_received,
        "latency_ms": row.latency_ms,
        "occurred_at": row.occurred_at,
    }


def _system_setting_to_dict(row: SystemSettingRow) -> dict:
    return {
        "key": row.key,
        "value": row.value,
        "version": row.version,
        "updated_by": row.updated_by,
        "updated_at": row.updated_at,
    }


def _user_to_dict(row: UserRow) -> dict:
    return {
        "id": row.id,
        "first_name": row.first_name,
        "last_name": row.last_name,
        "email": row.email,
        "organization_id": row.organization_id,
        "job_title": row.job_title,
        "department": row.department,
        "phone": row.phone,
        "country": row.country,
        "state_region": row.state_region,
        "primary_use_case": row.primary_use_case,
        "market_experience": row.market_experience,
        "role_id": row.role_id,
        "status": row.status,
        "expiration_at": row.expiration_at,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "activated_at": row.activated_at,
        "last_login_at": row.last_login_at,
    }


def _magic_link_token_to_dict(row: MagicLinkTokenRow) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "token_hash": row.token_hash,
        "purpose": row.purpose,
        "created_at": row.created_at,
        "expires_at": row.expires_at,
        "consumed_at": row.consumed_at,
        "revoked_at": row.revoked_at,
        "requested_ip": row.requested_ip,
        "user_agent": row.user_agent,
    }


def _session_to_dict(row: SessionRow) -> dict:
    return {
        "id": row.id,
        "user_id": row.user_id,
        "created_at": row.created_at,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
        "ip_address": row.ip_address,
        "user_agent": row.user_agent,
        "last_seen_at": row.last_seen_at,
    }


def _naive_utc(dt: datetime | None) -> datetime | None:
    """Normalizes to a naive UTC `datetime` before binding to a `DateTime` column.

    The schemas across this codebase mix naive (`datetime.utcnow()` defaults) and
    timezone-aware datetimes for what's conceptually the same "naive UTC" convention.
    sqlite silently tolerates that mix; `asyncpg`'s timestamp encoder does not — it
    raises `TypeError: can't subtract offset-naive and offset-aware datetimes` when an
    aware value reaches a `TIMESTAMP WITHOUT TIME ZONE` column, which real-Postgres
    validation of this repository surfaced.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class SqlAppRepository:
    """Durable, write-through persistence for `AppState`'s trading objects.

    `AppState` keeps its existing in-memory dicts as the router-facing read path (so
    no router code changes are needed); every mutation additionally writes through to
    this repository, and `hydrate()` reloads everything from the DB on boot so state
    survives a process restart. Deliberately decoupled from `apps/api` — it only knows
    about `schemas` types (safe: `packages/db` already depends on `alphagasiq-schemas`)
    plus plain primitives for the one app-local type (`Approval`), so `apps/api` maps
    to/from its own model at the call site instead of this package importing it.
    """

    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = build_engine(database_url)
        self.session_factory: async_sessionmaker = build_sessionmaker(self.engine)

    async def init_schema(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def seed_rbac_defaults(self) -> None:
        """Seeds the 8 fixed roles, the full permission-key list, and each role's
        default grants (see the module-level `_ROLE_NAMES`/`_PERMISSION_KEYS`/
        `_ROLE_PERMISSIONS` constants above). Idempotent — safe to call on every
        process boot; only inserts rows that don't already exist, so an admin who
        edits a role's grants in a later milestone won't have that edit reverted by
        the next restart re-running this seed."""
        async with self.session_factory() as session:
            existing_role_names = set((await session.execute(select(RoleRow.name))).scalars().all())
            for name in _ROLE_NAMES:
                if name not in existing_role_names:
                    session.add(RoleRow(name=name))

            existing_permission_keys = set((await session.execute(select(PermissionRow.key))).scalars().all())
            for key in _PERMISSION_KEYS:
                if key not in existing_permission_keys:
                    session.add(PermissionRow(key=key))

            await session.flush()

            role_id_by_name = {r.name: r.id for r in (await session.execute(select(RoleRow))).scalars().all()}
            permission_id_by_key = {
                p.key: p.id for p in (await session.execute(select(PermissionRow))).scalars().all()
            }
            existing_grants = {
                (rp.role_id, rp.permission_id)
                for rp in (await session.execute(select(RolePermissionRow))).scalars().all()
            }

            for role_name, permission_keys in _ROLE_PERMISSIONS.items():
                role_id = role_id_by_name[role_name]
                for key in permission_keys:
                    permission_id = permission_id_by_key[key]
                    if (role_id, permission_id) not in existing_grants:
                        session.add(RolePermissionRow(role_id=role_id, permission_id=permission_id))

            await session.commit()

    async def get_permission_keys_for_role(self, role_name: str) -> set[str]:
        """The effective permission set for one DB role — used by
        `apps/api/api_app/entitlements.py::get_effective_permissions`."""
        async with self.session_factory() as session:
            role = (await session.execute(select(RoleRow).where(RoleRow.name == role_name))).scalar_one_or_none()
            if role is None:
                return set()
            keys = (
                await session.execute(
                    select(PermissionRow.key)
                    .join(RolePermissionRow, RolePermissionRow.permission_id == PermissionRow.id)
                    .where(RolePermissionRow.role_id == role.id)
                )
            ).scalars().all()
        return set(keys)

    async def seed_feature_defaults(self) -> None:
        """Seeds the feature catalog and each role's default feature grants (module-
        level `_FEATURES`/`_ROLE_FEATURES` above) — the Milestone 4 counterpart to
        `seed_rbac_defaults`. Idempotent for the same reason: safe on every boot,
        never reverts an admin's later edit to an existing grant."""
        async with self.session_factory() as session:
            existing_feature_keys = set((await session.execute(select(FeatureRow.key))).scalars().all())
            for key, name, security_sensitive in _FEATURES:
                if key not in existing_feature_keys:
                    session.add(FeatureRow(key=key, name=name, security_sensitive=security_sensitive))
            await session.flush()

            role_id_by_name = {r.name: r.id for r in (await session.execute(select(RoleRow))).scalars().all()}
            feature_id_by_key = {f.key: f.id for f in (await session.execute(select(FeatureRow))).scalars().all()}
            existing_grants = {
                (rfe.role_id, rfe.feature_id)
                for rfe in (await session.execute(select(RoleFeatureEntitlementRow))).scalars().all()
            }

            for role_name, feature_keys in _ROLE_FEATURES.items():
                role_id = role_id_by_name.get(role_name)
                if role_id is None:
                    continue
                for key in feature_keys:
                    feature_id = feature_id_by_key[key]
                    if (role_id, feature_id) not in existing_grants:
                        session.add(RoleFeatureEntitlementRow(role_id=role_id, feature_id=feature_id, enabled=True))

            await session.commit()

    async def list_features(self) -> list[dict]:
        async with self.session_factory() as session:
            rows = (await session.execute(select(FeatureRow).order_by(FeatureRow.key))).scalars().all()
        return [
            {
                "id": r.id,
                "key": r.key,
                "name": r.name,
                "description": r.description,
                "security_sensitive": r.security_sensitive,
                "globally_enabled": r.globally_enabled,
            }
            for r in rows
        ]

    async def get_role_feature_keys(self, role_id: str) -> set[str]:
        """The set of feature keys a role explicitly grants (enabled=True rows only —
        role-level access is deny-by-default)."""
        async with self.session_factory() as session:
            keys = (
                await session.execute(
                    select(FeatureRow.key)
                    .join(RoleFeatureEntitlementRow, RoleFeatureEntitlementRow.feature_id == FeatureRow.id)
                    .where(RoleFeatureEntitlementRow.role_id == role_id, RoleFeatureEntitlementRow.enabled.is_(True))
                )
            ).scalars().all()
        return set(keys)

    async def get_organization_feature_overrides(self, organization_id: str) -> dict[str, bool]:
        """feature_key -> enabled, for every explicit org-level row. Absence of a key
        means the org places no restriction beyond the user's role."""
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(FeatureRow.key, OrganizationFeatureEntitlementRow.enabled)
                    .join(FeatureRow, OrganizationFeatureEntitlementRow.feature_id == FeatureRow.id)
                    .where(OrganizationFeatureEntitlementRow.organization_id == organization_id)
                )
            ).all()
        return {key: enabled for key, enabled in rows}

    async def get_user_feature_overrides(self, user_id: str) -> dict[str, bool]:
        """feature_key -> enabled, for every explicit per-user override row."""
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(FeatureRow.key, UserFeatureOverrideRow.enabled)
                    .join(FeatureRow, UserFeatureOverrideRow.feature_id == FeatureRow.id)
                    .where(UserFeatureOverrideRow.user_id == user_id)
                )
            ).all()
        return {key: enabled for key, enabled in rows}

    async def set_organization_feature_override(self, *, organization_id: str, feature_key: str, enabled: bool) -> None:
        async with self.session_factory() as session:
            feature = (await session.execute(select(FeatureRow).where(FeatureRow.key == feature_key))).scalar_one_or_none()
            if feature is None:
                raise ValueError(f"Unknown feature key: {feature_key}")
            existing = (
                await session.execute(
                    select(OrganizationFeatureEntitlementRow).where(
                        OrganizationFeatureEntitlementRow.organization_id == organization_id,
                        OrganizationFeatureEntitlementRow.feature_id == feature.id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.enabled = enabled
            else:
                session.add(
                    OrganizationFeatureEntitlementRow(organization_id=organization_id, feature_id=feature.id, enabled=enabled)
                )
            await session.commit()

    async def set_user_feature_override(self, *, user_id: str, feature_key: str, enabled: bool) -> None:
        async with self.session_factory() as session:
            feature = (await session.execute(select(FeatureRow).where(FeatureRow.key == feature_key))).scalar_one_or_none()
            if feature is None:
                raise ValueError(f"Unknown feature key: {feature_key}")
            existing = (
                await session.execute(
                    select(UserFeatureOverrideRow).where(
                        UserFeatureOverrideRow.user_id == user_id,
                        UserFeatureOverrideRow.feature_id == feature.id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.enabled = enabled
            else:
                session.add(UserFeatureOverrideRow(user_id=user_id, feature_id=feature.id, enabled=enabled))
            await session.commit()

    async def set_feature_globally_enabled(self, feature_key: str, enabled: bool) -> dict:
        """Milestone 6 "Feature Management" (spec §34) — the global on/off switch a
        `Feature` row's `globally_enabled` column already models; this just exposes
        writing it."""
        async with self.session_factory() as session:
            feature = (await session.execute(select(FeatureRow).where(FeatureRow.key == feature_key))).scalar_one_or_none()
            if feature is None:
                raise ValueError(f"Unknown feature key: {feature_key}")
            feature.globally_enabled = enabled
            await session.commit()
            await session.refresh(feature)
        return {
            "id": feature.id,
            "key": feature.key,
            "name": feature.name,
            "description": feature.description,
            "security_sensitive": feature.security_sensitive,
            "globally_enabled": feature.globally_enabled,
        }

    async def set_role_feature_entitlement(self, *, role_id: str, feature_key: str, enabled: bool) -> None:
        async with self.session_factory() as session:
            feature = (await session.execute(select(FeatureRow).where(FeatureRow.key == feature_key))).scalar_one_or_none()
            if feature is None:
                raise ValueError(f"Unknown feature key: {feature_key}")
            existing = (
                await session.execute(
                    select(RoleFeatureEntitlementRow).where(
                        RoleFeatureEntitlementRow.role_id == role_id,
                        RoleFeatureEntitlementRow.feature_id == feature.id,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                existing.enabled = enabled
            else:
                session.add(RoleFeatureEntitlementRow(role_id=role_id, feature_id=feature.id, enabled=enabled))
            await session.commit()

    # -- system settings (spec §38) ----------------------------------------------------

    async def seed_system_settings_defaults(self) -> None:
        """Idempotent: only inserts a key if it doesn't already exist, so an admin's
        prior edit is never reverted by a later restart re-running this seed."""
        async with self.session_factory() as session:
            existing_keys = set((await session.execute(select(SystemSettingRow.key))).scalars().all())
            for key, value in _SYSTEM_SETTINGS_DEFAULTS.items():
                if key not in existing_keys:
                    session.add(SystemSettingRow(key=key, value=value, version=1))
            await session.commit()

    async def list_system_settings(self) -> list[dict]:
        async with self.session_factory() as session:
            rows = (await session.execute(select(SystemSettingRow).order_by(SystemSettingRow.key))).scalars().all()
        return [_system_setting_to_dict(r) for r in rows]

    async def get_system_setting(self, key: str) -> dict | None:
        async with self.session_factory() as session:
            row = (await session.execute(select(SystemSettingRow).where(SystemSettingRow.key == key))).scalar_one_or_none()
        return _system_setting_to_dict(row) if row is not None else None

    async def set_system_setting(self, key: str, value: object, *, updated_by: str | None) -> dict:
        """Writes the new value and appends the row's *previous* state to
        `system_setting_history` first — so history is always "what it used to be,"
        letting an admin see (and manually revert to) any prior version."""
        async with self.session_factory() as session:
            row = (await session.execute(select(SystemSettingRow).where(SystemSettingRow.key == key))).scalar_one_or_none()
            if row is None:
                raise ValueError(f"Unknown system setting key: {key}")
            session.add(
                SystemSettingHistoryRow(
                    key=row.key, value=row.value, version=row.version, changed_by=row.updated_by, changed_at=row.updated_at
                )
            )
            row.value = value
            row.version += 1
            row.updated_by = updated_by
            row.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(row)
        return _system_setting_to_dict(row)

    async def list_system_setting_history(self, key: str) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(SystemSettingHistoryRow)
                        .where(SystemSettingHistoryRow.key == key)
                        .order_by(SystemSettingHistoryRow.version.desc())
                    )
                )
                .scalars()
                .all()
            )
        return [
            {
                "id": r.id,
                "key": r.key,
                "value": r.value,
                "version": r.version,
                "changed_by": r.changed_by,
                "changed_at": r.changed_at,
            }
            for r in rows
        ]

    # -- admin: user profile edits ------------------------------------------------------

    async def update_user_profile(self, user_id: str, **fields) -> dict | None:
        """Milestone 6 "Edit user profile" / "Change organization" / "Change role" /
        "Set account expiration" (spec §32). Only the keys actually passed are
        updated — the caller (the admin API layer) decides which fields a request
        touched; this never overwrites a field with `None` unless `None` was
        explicitly passed for it."""
        async with self.session_factory() as session:
            row = (await session.execute(select(UserRow).where(UserRow.id == user_id))).scalar_one_or_none()
            if row is None:
                return None
            for field, value in fields.items():
                setattr(row, field, value)
            row.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(row)
        return _user_to_dict(row)

    async def update_organization(self, organization_id: str, **fields) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(OrganizationRow).where(OrganizationRow.id == organization_id))
            ).scalar_one_or_none()
            if row is None:
                return None
            for field, value in fields.items():
                setattr(row, field, value)
            row.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(row)
        return _organization_to_dict(row)

    # -- data feed administration (spec §§35-37) ---------------------------------------

    async def seed_data_feed_configs(self, provider_ids: list[str]) -> None:
        """Idempotent: seeds one default config row per currently-registered
        provider id. Safe to re-run on every boot (e.g. after a new connector is
        registered) without touching an admin's prior edits to an existing row."""
        async with self.session_factory() as session:
            existing = set((await session.execute(select(DataFeedConfigRow.provider_id))).scalars().all())
            for provider_id in provider_ids:
                if provider_id not in existing:
                    session.add(DataFeedConfigRow(provider_id=provider_id))
            await session.commit()

    async def list_data_feed_configs(self) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (await session.execute(select(DataFeedConfigRow).order_by(DataFeedConfigRow.provider_id)))
                .scalars()
                .all()
            )
        return [_data_feed_config_to_dict(r) for r in rows]

    async def get_data_feed_config(self, provider_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(DataFeedConfigRow).where(DataFeedConfigRow.provider_id == provider_id))
            ).scalar_one_or_none()
        return _data_feed_config_to_dict(row) if row is not None else None

    async def update_data_feed_config(self, provider_id: str, **fields) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(DataFeedConfigRow).where(DataFeedConfigRow.provider_id == provider_id))
            ).scalar_one_or_none()
            if row is None:
                return None
            for field, value in fields.items():
                setattr(row, field, value)
            row.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(row)
        return _data_feed_config_to_dict(row)

    async def record_data_feed_event(
        self,
        *,
        provider_id: str,
        event_type: str,
        status: str,
        detail: str = "",
        records_received: int | None = None,
        latency_ms: float | None = None,
    ) -> dict:
        row = DataFeedEventRow(
            provider_id=provider_id,
            event_type=event_type,
            status=status,
            detail=detail,
            records_received=records_received,
            latency_ms=latency_ms,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return _data_feed_event_to_dict(row)

    async def list_data_feed_events(self, provider_id: str, *, limit: int = 50) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(DataFeedEventRow)
                        .where(DataFeedEventRow.provider_id == provider_id)
                        .order_by(DataFeedEventRow.occurred_at.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [_data_feed_event_to_dict(r) for r in rows]

    async def list_roles(self) -> list[dict]:
        async with self.session_factory() as session:
            rows = (await session.execute(select(RoleRow).order_by(RoleRow.name))).scalars().all()
        return [_role_to_dict(r) for r in rows]

    async def get_role_by_name(self, name: str) -> dict | None:
        async with self.session_factory() as session:
            row = (await session.execute(select(RoleRow).where(RoleRow.name == name))).scalar_one_or_none()
        return _role_to_dict(row) if row is not None else None

    async def get_role_by_id(self, role_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (await session.execute(select(RoleRow).where(RoleRow.id == role_id))).scalar_one_or_none()
        return _role_to_dict(row) if row is not None else None

    async def create_organization(
        self,
        *,
        name: str,
        website: str | None = None,
        industry: str | None = None,
        company_type: str | None = None,
        country: str | None = None,
        state_region: str | None = None,
        billing_plan: str | None = None,
        account_owner: str | None = None,
        primary_contact: str | None = None,
        feature_package: str | None = None,
        notes: str | None = None,
    ) -> dict:
        row = OrganizationRow(
            name=name,
            website=website,
            industry=industry,
            company_type=company_type,
            country=country,
            state_region=state_region,
            billing_plan=billing_plan,
            account_owner=account_owner,
            primary_contact=primary_contact,
            feature_package=feature_package,
            notes=notes,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return _organization_to_dict(row)

    async def find_organization_by_name(self, name: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(OrganizationRow).where(OrganizationRow.name == name))
            ).scalar_one_or_none()
        return _organization_to_dict(row) if row is not None else None

    async def get_organization(self, organization_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(OrganizationRow).where(OrganizationRow.id == organization_id))
            ).scalar_one_or_none()
        return _organization_to_dict(row) if row is not None else None

    async def list_organizations(self) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (await session.execute(select(OrganizationRow).order_by(OrganizationRow.name))).scalars().all()
            )
        return [_organization_to_dict(r) for r in rows]

    async def create_user(
        self,
        *,
        first_name: str,
        last_name: str,
        email: str,
        organization_id: str,
        role_id: str,
        status: str,
        job_title: str | None = None,
        department: str | None = None,
        phone: str | None = None,
        country: str | None = None,
        state_region: str | None = None,
        primary_use_case: str | None = None,
        market_experience: str | None = None,
        expiration_at: datetime | None = None,
        created_by: str | None = None,
    ) -> dict:
        """Creates a `User` row. This is only ever called from the authenticated
        admin-create-user endpoint (`POST /admin/users`) — there is no other writer,
        by design (see docs/access-model.md "No Self-Registration")."""
        row = UserRow(
            first_name=first_name,
            last_name=last_name,
            email=email.lower(),
            organization_id=organization_id,
            job_title=job_title,
            department=department,
            phone=phone,
            country=country,
            state_region=state_region,
            primary_use_case=primary_use_case,
            market_experience=market_experience,
            role_id=role_id,
            status=status,
            expiration_at=_naive_utc(expiration_at),
            created_by=created_by,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return _user_to_dict(row)

    async def get_user_by_email(self, email: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(UserRow).where(UserRow.email == email.lower()))
            ).scalar_one_or_none()
        return _user_to_dict(row) if row is not None else None

    async def get_user_by_id(self, user_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (await session.execute(select(UserRow).where(UserRow.id == user_id))).scalar_one_or_none()
        return _user_to_dict(row) if row is not None else None

    async def list_users(self) -> list[dict]:
        async with self.session_factory() as session:
            rows = (await session.execute(select(UserRow).order_by(UserRow.created_at.desc()))).scalars().all()
        return [_user_to_dict(r) for r in rows]

    async def update_user_status(self, user_id: str, status: str) -> dict | None:
        async with self.session_factory() as session:
            row = (await session.execute(select(UserRow).where(UserRow.id == user_id))).scalar_one_or_none()
            if row is None:
                return None
            row.status = status
            row.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(row)
        return _user_to_dict(row)

    async def mark_user_activated(self, user_id: str) -> dict | None:
        """Promotes an `INVITED` user to `ACTIVE` and stamps `activated_at`/
        `last_login_at` — called only from a successful magic-link verification
        (`GET /auth/magic-link/verify`), never by any admin-facing endpoint (see
        docs/access-model.md §2: INVITED->ACTIVE only ever happens this way)."""
        now = datetime.utcnow()
        async with self.session_factory() as session:
            row = (await session.execute(select(UserRow).where(UserRow.id == user_id))).scalar_one_or_none()
            if row is None:
                return None
            row.status = "ACTIVE"
            row.activated_at = row.activated_at or now
            row.last_login_at = now
            row.updated_at = now
            await session.commit()
            await session.refresh(row)
        return _user_to_dict(row)

    async def record_user_login(self, user_id: str) -> None:
        async with self.session_factory() as session:
            row = (await session.execute(select(UserRow).where(UserRow.id == user_id))).scalar_one_or_none()
            if row is None:
                return
            row.last_login_at = datetime.utcnow()
            await session.commit()

    # -- magic link tokens ------------------------------------------------------------

    async def create_magic_link_token(
        self,
        *,
        user_id: str,
        token_hash: str,
        purpose: str,
        expires_at: datetime,
        requested_ip: str | None = None,
        user_agent: str | None = None,
    ) -> dict:
        row = MagicLinkTokenRow(
            user_id=user_id,
            token_hash=token_hash,
            purpose=purpose,
            expires_at=_naive_utc(expires_at),
            requested_ip=requested_ip,
            user_agent=user_agent,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return _magic_link_token_to_dict(row)

    async def get_magic_link_token_by_hash(self, token_hash: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(MagicLinkTokenRow).where(MagicLinkTokenRow.token_hash == token_hash))
            ).scalar_one_or_none()
        return _magic_link_token_to_dict(row) if row is not None else None

    async def consume_magic_link_token(self, token_id: str) -> dict | None:
        """Marks a token consumed. Applying this exactly once (verified by the caller
        checking `consumed_at is None` before calling) is what makes the token
        single-use — spec §19's "Immediate invalidation after use"."""
        async with self.session_factory() as session:
            row = (
                await session.execute(select(MagicLinkTokenRow).where(MagicLinkTokenRow.id == token_id))
            ).scalar_one_or_none()
            if row is None:
                return None
            row.consumed_at = datetime.utcnow()
            await session.commit()
            await session.refresh(row)
        return _magic_link_token_to_dict(row)

    async def revoke_unconsumed_magic_link_tokens_for_user(self, user_id: str, *, purpose: str | None = None) -> int:
        """Invalidates every outstanding (unconsumed, unrevoked) token for a user —
        used both by "Resend Invitation" (spec §18: "Invalidate all prior unused
        invitation links") and defensively whenever a fresh token is issued for the
        same purpose, so an old email link can never be used alongside a new one."""
        async with self.session_factory() as session:
            stmt = select(MagicLinkTokenRow).where(
                MagicLinkTokenRow.user_id == user_id,
                MagicLinkTokenRow.consumed_at.is_(None),
                MagicLinkTokenRow.revoked_at.is_(None),
            )
            if purpose is not None:
                stmt = stmt.where(MagicLinkTokenRow.purpose == purpose)
            rows = (await session.execute(stmt)).scalars().all()
            now = datetime.utcnow()
            for row in rows:
                row.revoked_at = now
            await session.commit()
        return len(rows)

    # -- sessions -----------------------------------------------------------------

    async def create_session(
        self, *, user_id: str, expires_at: datetime, ip_address: str | None = None, user_agent: str | None = None
    ) -> dict:
        row = SessionRow(user_id=user_id, expires_at=_naive_utc(expires_at), ip_address=ip_address, user_agent=user_agent)
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return _session_to_dict(row)

    async def get_session(self, session_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (await session.execute(select(SessionRow).where(SessionRow.id == session_id))).scalar_one_or_none()
        return _session_to_dict(row) if row is not None else None

    async def list_sessions_for_user(self, user_id: str) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(SessionRow).where(SessionRow.user_id == user_id).order_by(SessionRow.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
        return [_session_to_dict(r) for r in rows]

    async def revoke_session(self, session_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (await session.execute(select(SessionRow).where(SessionRow.id == session_id))).scalar_one_or_none()
            if row is None:
                return None
            row.revoked_at = datetime.utcnow()
            await session.commit()
            await session.refresh(row)
        return _session_to_dict(row)

    async def touch_session(self, session_id: str) -> None:
        async with self.session_factory() as session:
            row = (await session.execute(select(SessionRow).where(SessionRow.id == session_id))).scalar_one_or_none()
            if row is None:
                return
            row.last_seen_at = datetime.utcnow()
            await session.commit()

    # -- chat conversations (spec §29) -------------------------------------------------

    async def create_chat_conversation(self, *, conversation_id: str, user_id: str, organization_id: str | None) -> dict:
        row = ChatConversationRow(id=conversation_id, user_id=user_id, organization_id=organization_id)
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
        return {"id": row.id, "user_id": row.user_id, "organization_id": row.organization_id, "created_at": row.created_at}

    async def save_chat_message(
        self,
        *,
        conversation_id: str,
        role: str,
        content: str,
        citations: list | None = None,
        freshness: dict | None = None,
        tool_used: str | None = None,
        model: str | None = None,
        latency_ms: float | None = None,
        permissions_context: dict | None = None,
    ) -> dict:
        """Persists one chat turn. Deliberately has no field for a private
        chain-of-thought — only what a `ChatMessage` API response already exposes,
        plus metadata about how it was produced (spec §29)."""
        row = ChatMessageRow(
            conversation_id=conversation_id,
            role=role,
            content=content,
            citations=citations or [],
            freshness=freshness or {},
            tool_used=tool_used,
            model=model,
            latency_ms=latency_ms,
            permissions_context=permissions_context or {},
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return {
            "id": row.id,
            "conversation_id": row.conversation_id,
            "role": row.role,
            "content": row.content,
            "citations": row.citations,
            "freshness": row.freshness,
            "tool_used": row.tool_used,
            "model": row.model,
            "latency_ms": row.latency_ms,
            "permissions_context": row.permissions_context,
            "created_at": row.created_at,
        }

    async def get_chat_conversation(self, conversation_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(ChatConversationRow).where(ChatConversationRow.id == conversation_id))
            ).scalar_one_or_none()
        if row is None:
            return None
        return {"id": row.id, "user_id": row.user_id, "organization_id": row.organization_id, "created_at": row.created_at}

    async def list_chat_messages(self, conversation_id: str) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(ChatMessageRow)
                        .where(ChatMessageRow.conversation_id == conversation_id)
                        .order_by(ChatMessageRow.created_at)
                    )
                )
                .scalars()
                .all()
            )
        return [
            {
                "id": r.id,
                "conversation_id": r.conversation_id,
                "role": r.role,
                "content": r.content,
                "citations": r.citations,
                "freshness": r.freshness,
                "tool_used": r.tool_used,
                "model": r.model,
                "latency_ms": r.latency_ms,
                "permissions_context": r.permissions_context,
                "created_at": r.created_at,
            }
            for r in rows
        ]

    async def list_chat_conversations(self, *, user_id: str | None = None) -> list[dict]:
        """Admin-visibility listing (spec §29: "Support administrator access to chat
        usage metadata according to role and policy") — filterable by user."""
        async with self.session_factory() as session:
            stmt = select(ChatConversationRow).order_by(ChatConversationRow.created_at.desc())
            if user_id is not None:
                stmt = stmt.where(ChatConversationRow.user_id == user_id)
            rows = (await session.execute(stmt)).scalars().all()
        return [
            {"id": r.id, "user_id": r.user_id, "organization_id": r.organization_id, "created_at": r.created_at}
            for r in rows
        ]

    # -- writes ---------------------------------------------------------------------

    async def save_trade_idea(self, trade: TradeIdea, forecast: PriceForecast | None) -> None:
        row = TradeIdeaRow(
            trade_id=str(trade.trade_id),
            strategy=trade.strategy,
            instrument=trade.instrument,
            instrument_type=trade.instrument_type.value,
            direction=trade.direction.value,
            entry=trade.entry,
            target=trade.target,
            stop_or_invalidation=trade.stop_or_invalidation,
            time_horizon=trade.time_horizon,
            expected_return=trade.expected_return,
            expected_loss=trade.expected_loss,
            probability_success=trade.probability_success,
            confidence=trade.confidence,
            thesis=trade.thesis,
            catalysts=trade.catalysts,
            risks=trade.risks,
            invalidation_conditions=trade.invalidation_conditions,
            supporting_data=trade.supporting_data,
            source_citations=trade.source_citations,
            created_at=_naive_utc(trade.created_at),
            expires_at=_naive_utc(trade.expires_at),
            forecast=forecast.model_dump(mode="json") if forecast is not None else None,
        )
        async with self.session_factory() as session:
            await session.merge(row)
            await session.commit()

    async def save_committee_decision(self, trade_id: UUID, decision: InvestmentCommitteeDecision) -> None:
        row = CommitteeDecisionRow(
            original_trade_id=str(trade_id),
            original_trade=decision.original_trade.model_dump(mode="json"),
            bull_case=decision.bull_case,
            bear_case=decision.bear_case,
            skeptic_case=decision.skeptic_case,
            data_quality_assessment=decision.data_quality_assessment,
            portfolio_effect=decision.portfolio_effect,
            consensus_score=decision.consensus_score,
            unresolved_questions=decision.unresolved_questions,
            recommended_action=decision.recommended_action.value,
            decided_at=_naive_utc(decision.decided_at),
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    async def save_risk_check(self, trade_id: UUID, risk_check: RiskCheckResult) -> None:
        row = RiskCheckRow(
            check_id=str(risk_check.check_id),
            trade_id=str(trade_id),
            verdict=risk_check.verdict.value,
            rule_results=[r.model_dump(mode="json") for r in risk_check.rule_results],
            governor_version=risk_check.governor_version,
            evaluated_at=_naive_utc(risk_check.evaluated_at),
        )
        async with self.session_factory() as session:
            await session.merge(row)
            await session.commit()

    async def save_approval(
        self,
        *,
        approval_id: UUID,
        trade_id: UUID,
        state: str,
        actions: list[dict],
        updated_at: datetime,
    ) -> None:
        row = ApprovalRow(
            id=str(approval_id),
            trade_id=str(trade_id),
            state=state,
            actions=actions,
            updated_at=_naive_utc(updated_at),
        )
        async with self.session_factory() as session:
            await session.merge(row)
            await session.commit()

    async def append_decision_journal_entry(self, trade_id: UUID, entry: dict) -> None:
        row = DecisionJournalRow(trade_id=str(trade_id), entry=entry)
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    async def save_post_trade_analysis(self, analysis: PostTradeAnalysis) -> None:
        row = PostTradeAnalysisRow(
            id=str(analysis.id),
            trade_id=str(analysis.trade_id),
            expected_outcome=analysis.expected_outcome,
            actual_outcome=analysis.actual_outcome,
            forecast_error=analysis.forecast_error,
            thesis_accuracy=analysis.thesis_accuracy,
            timing_accuracy=analysis.timing_accuracy,
            risk_accuracy=analysis.risk_accuracy,
            model_contribution=analysis.model_contribution,
            unexpected_events=analysis.unexpected_events,
            lessons=analysis.lessons,
            quadrant=analysis.quadrant.value,
            quant_model_type=analysis.quant_model_type.value if analysis.quant_model_type else None,
            quant_model_version=analysis.quant_model_version,
            quant_predicted_return=analysis.quant_predicted_return,
            quant_forecast_error=analysis.quant_forecast_error,
            quant_up_probability=analysis.quant_up_probability,
            created_at=_naive_utc(analysis.created_at),
        )
        async with self.session_factory() as session:
            await session.merge(row)
            await session.commit()

    async def save_contact_inquiry(
        self,
        *,
        first_name: str,
        last_name: str,
        business_email: str,
        company_name: str,
        job_title: str | None,
        phone: str | None,
        inquiry_type: str,
        message: str,
    ) -> str:
        """Persists a /contact submission. Deliberately takes only plain business-
        inquiry fields — there is no path from here to a `User`/`Organization`/
        `MagicLinkToken` row; this table exists purely for admin visibility into
        inbound inquiries."""
        row = ContactInquiryRow(
            first_name=first_name,
            last_name=last_name,
            business_email=business_email,
            company_name=company_name,
            job_title=job_title,
            phone=phone,
            inquiry_type=inquiry_type,
            message=message,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
        return row.id

    async def list_contact_inquiries(self) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (await session.execute(select(ContactInquiryRow).order_by(ContactInquiryRow.created_at.desc())))
                .scalars()
                .all()
            )
        return [
            {
                "id": r.id,
                "first_name": r.first_name,
                "last_name": r.last_name,
                "business_email": r.business_email,
                "company_name": r.company_name,
                "job_title": r.job_title,
                "phone": r.phone,
                "inquiry_type": r.inquiry_type,
                "message": r.message,
                "created_at": r.created_at,
            }
            for r in rows
        ]

    async def save_risk_limits(self, limits: RiskLimits) -> None:
        row = RiskLimitsRow(
            max_position_size=limits.max_position_size,
            max_risk_per_trade=limits.max_risk_per_trade,
            max_daily_loss=limits.max_daily_loss,
            max_drawdown=limits.max_drawdown,
            max_portfolio_var=limits.max_portfolio_var,
            max_sector_exposure=limits.max_sector_exposure,
            max_contract_exposure=limits.max_contract_exposure,
            max_correlated_exposure=limits.max_correlated_exposure,
            effective_from=_naive_utc(limits.effective_from),
            effective_to=_naive_utc(limits.effective_to),
            set_by_user_id=limits.set_by_user_id,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    # -- hydration --------------------------------------------------------------------

    async def hydrate(self) -> dict:
        """Reloads every persisted object, keyed by trade_id/approval_id (as `str`,
        matching how they're stored) so `AppState` can key its in-memory dicts by
        `UUID(...)` of each key. Returns an empty-but-well-shaped dict when the DB has
        nothing yet (first boot) — safe for `AppState` to iterate unconditionally.
        """
        async with self.session_factory() as session:
            trade_rows = (await session.execute(select(TradeIdeaRow))).scalars().all()
            decision_rows = (await session.execute(select(CommitteeDecisionRow))).scalars().all()
            risk_check_rows = (await session.execute(select(RiskCheckRow))).scalars().all()
            approval_rows = (await session.execute(select(ApprovalRow))).scalars().all()
            journal_rows = (
                (await session.execute(select(DecisionJournalRow).order_by(DecisionJournalRow.created_at)))
                .scalars()
                .all()
            )
            post_trade_rows = (await session.execute(select(PostTradeAnalysisRow))).scalars().all()
            limits_rows = (
                (await session.execute(select(RiskLimitsRow).order_by(RiskLimitsRow.effective_from.desc())))
                .scalars()
                .all()
            )

        trade_ideas: dict[str, TradeIdea] = {}
        forecasts: dict[str, PriceForecast] = {}
        for row in trade_rows:
            trade_ideas[row.trade_id] = TradeIdea(
                trade_id=UUID(row.trade_id),
                strategy=row.strategy,
                instrument=row.instrument,
                instrument_type=row.instrument_type,
                direction=row.direction,
                entry=row.entry,
                target=row.target,
                stop_or_invalidation=row.stop_or_invalidation,
                time_horizon=row.time_horizon,
                expected_return=row.expected_return,
                expected_loss=row.expected_loss,
                probability_success=row.probability_success,
                confidence=row.confidence,
                thesis=row.thesis,
                catalysts=row.catalysts,
                risks=row.risks,
                invalidation_conditions=row.invalidation_conditions,
                supporting_data=row.supporting_data,
                source_citations=row.source_citations,
                created_at=row.created_at,
                expires_at=row.expires_at,
            )
            if row.forecast is not None:
                forecasts[row.trade_id] = PriceForecast.model_validate(row.forecast)

        committee_decisions: dict[str, InvestmentCommitteeDecision] = {}
        for row in decision_rows:
            committee_decisions[row.original_trade_id] = InvestmentCommitteeDecision(
                original_trade=TradeIdea.model_validate(row.original_trade),
                bull_case=row.bull_case,
                bear_case=row.bear_case,
                skeptic_case=row.skeptic_case,
                data_quality_assessment=row.data_quality_assessment,
                portfolio_effect=row.portfolio_effect,
                consensus_score=row.consensus_score,
                unresolved_questions=row.unresolved_questions,
                recommended_action=row.recommended_action,
                decided_at=row.decided_at,
            )

        risk_checks: dict[str, RiskCheckResult] = {}
        for row in risk_check_rows:
            risk_checks[row.trade_id] = RiskCheckResult(
                check_id=UUID(row.check_id),
                trade_id=UUID(row.trade_id),
                verdict=row.verdict,
                rule_results=row.rule_results,
                governor_version=row.governor_version,
                evaluated_at=row.evaluated_at,
            )

        approvals: list[dict] = [
            {
                "id": row.id,
                "trade_id": row.trade_id,
                "state": row.state,
                "actions": row.actions,
                "updated_at": row.updated_at,
            }
            for row in approval_rows
        ]

        decision_journal: dict[str, list[dict]] = {}
        for row in journal_rows:
            decision_journal.setdefault(row.trade_id, []).append(row.entry)

        post_trade_analyses: dict[str, PostTradeAnalysis] = {}
        for row in post_trade_rows:
            post_trade_analyses[row.trade_id] = PostTradeAnalysis(
                id=UUID(row.id),
                trade_id=UUID(row.trade_id),
                expected_outcome=row.expected_outcome,
                actual_outcome=row.actual_outcome,
                forecast_error=row.forecast_error,
                thesis_accuracy=row.thesis_accuracy,
                timing_accuracy=row.timing_accuracy,
                risk_accuracy=row.risk_accuracy,
                model_contribution=row.model_contribution,
                unexpected_events=row.unexpected_events,
                lessons=row.lessons,
                quadrant=row.quadrant,
                quant_model_type=row.quant_model_type,
                quant_model_version=row.quant_model_version,
                quant_predicted_return=row.quant_predicted_return,
                quant_forecast_error=row.quant_forecast_error,
                quant_up_probability=row.quant_up_probability,
                created_at=row.created_at,
            )

        risk_limits: RiskLimits | None = None
        if limits_rows:
            latest = limits_rows[0]
            risk_limits = RiskLimits(
                max_position_size=latest.max_position_size,
                max_risk_per_trade=latest.max_risk_per_trade,
                max_daily_loss=latest.max_daily_loss,
                max_drawdown=latest.max_drawdown,
                max_portfolio_var=latest.max_portfolio_var,
                max_sector_exposure=latest.max_sector_exposure,
                max_contract_exposure=latest.max_contract_exposure,
                max_correlated_exposure=latest.max_correlated_exposure,
                effective_from=latest.effective_from,
                effective_to=latest.effective_to,
                set_by_user_id=latest.set_by_user_id,
            )

        return {
            "trade_ideas": trade_ideas,
            "forecasts": forecasts,
            "committee_decisions": committee_decisions,
            "risk_checks": risk_checks,
            "approvals": approvals,
            "decision_journal": decision_journal,
            "post_trade_analyses": post_trade_analyses,
            "risk_limits": risk_limits,
        }
