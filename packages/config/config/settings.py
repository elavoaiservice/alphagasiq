from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"

    database_url: str = "sqlite+aiosqlite:///./alphagasiq_dev.db"
    redis_url: str = "redis://localhost:6379/0"
    event_bus_impl: str = "memory"  # memory | redpanda
    kafka_bootstrap_servers: str = "localhost:9092"

    # Neo4j-backed pipeline digital twin: additive, same config-gated pattern as
    # OIDC/redpanda above. When `neo4j_uri` is unset (every default dev/docker
    # environment), the pipeline graph stays the plain in-memory `PipelineGraph`
    # `pipeline_graph.py` already builds. When set, `AppState` seeds that same graph
    # into Neo4j and reloads it from there — a real round trip, not just a config flag.
    neo4j_uri: str | None = None
    neo4j_user: str = "neo4j"
    neo4j_password: str | None = None
    neo4j_database: str | None = None

    jwt_secret: str = "dev-secret-change-me-in-production-min-32-bytes"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    # This API's own externally-reachable base URL — used only to build the magic-link
    # URL emailed to a user (`{api_base_url}/api/v1/auth/magic-link/verify?token=...`).
    # Mirrors `oidc_redirect_uri` below, which is the same kind of "this service's own
    # public URL" value for the OIDC callback.
    api_base_url: str = "http://localhost:8000"

    # Real OIDC (Authorization Code + PKCE) sits behind the dev-mode password-grant
    # login: when `oidc_issuer_url` is unset (the default for every local/dev/docker
    # environment), only the existing dev login works and the /auth/oidc/* endpoints
    # report "not_configured" rather than erroring — the platform's consistent honest-
    # stub pattern (see EIA_API_KEY, CME_API_ID, etc.).
    oidc_issuer_url: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: str | None = None
    oidc_redirect_uri: str | None = None
    oidc_audience: str | None = None
    # Name of the ID token / userinfo claim carrying this platform's roles
    # (ADMIN/TRADER/RISK_MANAGER/RESEARCHER/VIEWER) — IdPs vary (custom claim,
    # namespaced claim like `https://alphagasiq/roles`, or an `groups` claim mapped
    # by the IdP's admin console), so this is configurable rather than hardcoded.
    oidc_roles_claim: str = "roles"
    # Roles granted to any authenticated OIDC user who has none of the above claim's
    # values recognized as a platform Role — VIEWER (read-only) is the safe default,
    # never an elevated role.
    oidc_default_roles: str = "VIEWER"

    # Magic-link auth (docs/access-model.md §3) + session lifetime (§4). Sessions are
    # DB-backed (`Session` table) so `magic_link_session_minutes` also bounds how long
    # a magic-link-issued JWT's `sid` claim stays valid server-side, independent of the
    # dev-mode/OIDC `jwt_expire_minutes` above (those tokens carry no `sid` and are
    # never looked up against the `sessions` table).
    magic_link_expire_minutes: int = 15
    magic_link_session_minutes: int = 480
    # Per-identifier (email or IP) request budget for POST /auth/magic-link/request —
    # an in-memory sliding window (`apps/api/api_app/rate_limit.py`), sufficient for a
    # single-process deployment; a multi-instance production deployment would back
    # this with Redis (`redis_url` above exists for exactly this, unused today) instead.
    magic_link_rate_limit_max_requests: int = 5
    magic_link_rate_limit_window_seconds: int = 900

    # Email service (docs/access-model.md §3, spec §57): `EmailProvider` abstraction in
    # `apps/api/api_app/email_service.py`. Unset `smtp_host` (every default dev/test
    # environment) selects `ConsoleEmailProvider`, which only logs the rendered email —
    # the platform's established honest-stub pattern (see OIDC/Neo4j/redpanda above);
    # setting `smtp_host` selects the real `SMTPEmailProvider`.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    email_from_address: str = "no-reply@alphagasiq.local"
    support_contact_email: str = "support@alphagasiq.local"

    anthropic_api_key: str | None = None
    eia_api_key: str | None = None
    noaa_api_token: str | None = None
    cme_api_id: str | None = None
    cme_api_secret: str | None = None
    ice_api_id: str | None = None
    ice_api_secret: str | None = None
    news_provider_api_key: str | None = None
    rss_news_feeds: str | None = None  # comma-separated RSS URLs → real (free) news
    # FERC eLibrary / pipeline EBBs have no stable public JSON API, so their
    # connectors are stubs. Keys are captured for when a connector is built.
    ferc_api_key: str | None = None
    pipeline_ebb_api_key: str | None = None
    # SEC EDGAR requires no API key, only a descriptive contact per its fair-access
    # policy (https://www.sec.gov/os/webmaster-faq#developers) — unlike every other
    # *_api_key setting here, leaving this unset does not disable the connector.
    sec_edgar_contact_email: str | None = None

    s3_endpoint_url: str | None = None
    s3_bucket: str = "alphagasiq-dev"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None

    use_mock_market_data: bool = True
    use_mock_news: bool = True

    cors_origins: str = "http://localhost:3000"

    # Observability (gap-closure follow-up): same config-gated pattern as
    # smtp_host/oidc_issuer_url/neo4j_uri/kafka_bootstrap_servers above -- unset
    # `sentry_dsn` (every default dev/test environment) means exception tracking is
    # never initialized at all, honestly, rather than silently no-op-ing against an
    # empty DSN. `log_level` governs the structured JSON request-logging middleware
    # (`apps/api/api_app/logging_config.py`), which is always active regardless of
    # Sentry configuration.
    sentry_dsn: str | None = None
    sentry_traces_sample_rate: float = 0.0
    log_level: str = "INFO"

    # Admin Upgrade page version panel (`apps/api/api_app/version.py`): which repo
    # and branch an upgrade pulls from. `upgrade_branch` unset means "the branch
    # this image was built from" (stamped into build-info.json), so a deployment
    # tracking a feature branch reports against that branch, not always `main`.
    # `github_token` is optional -- the repo is public today, so the version panel
    # works unauthenticated; a token only raises GitHub's 60-req/hour anonymous
    # rate limit, and would become required if the repo were ever made private.
    upgrade_repo: str = "elavoaiservice/alphagasiq"
    upgrade_branch: str | None = None
    github_token: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
