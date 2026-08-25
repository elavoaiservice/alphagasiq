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

    jwt_secret: str = "dev-secret-change-me-in-production-min-32-bytes"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

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
