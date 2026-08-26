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

    anthropic_api_key: str | None = None
    eia_api_key: str | None = None
    noaa_api_token: str | None = None
    cme_api_id: str | None = None
    cme_api_secret: str | None = None
    news_provider_api_key: str | None = None

    s3_endpoint_url: str | None = None
    s3_bucket: str = "alphagasiq-dev"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None

    use_mock_market_data: bool = True
    use_mock_news: bool = True

    cors_origins: str = "http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
