from __future__ import annotations

from contextlib import asynccontextmanager

from config import Settings, branding, get_settings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .logging_config import RequestLoggingMiddleware, configure_logging
from .routers import (
    admin_agent_versions,
    admin_agents,
    admin_console,
    admin_data_feeds,
    admin_data_governance,
    admin_enterprise_data,
    admin_governance,
    admin_models,
    admin_users,
    admin_workspaces,
    agents,
    alpha,
    alpha_enterprise,
    approvals,
    auth,
    chat,
    contact,
    enterprise_webhooks,
    fundamentals,
    journal,
    market,
    news,
    portfolio,
    quant,
    risk,
    trading,
)
from .state import get_app_state


@asynccontextmanager
async def _lifespan(app: FastAPI):
    state = await get_app_state()
    yield
    await state.repo.dispose()
    # Only RedpandaEventBus (EVENT_BUS_IMPL=redpanda) needs an explicit stop — it owns
    # background consumer tasks and a real network connection; InMemoryEventBus has
    # neither.
    stop = getattr(state.event_bus, "stop", None)
    if stop is not None:
        await stop()
    if state.neo4j_driver is not None:
        await state.neo4j_driver.close()


def _init_sentry_if_configured(settings: Settings) -> None:
    """Config-gated exactly like OIDC/SMTP/Neo4j elsewhere in this codebase:
    unset `sentry_dsn` (every default dev/test environment) means Sentry is
    never imported or initialized at all, not silently no-op'd against an
    empty DSN. Lazy import so `sentry-sdk` need not be importable for any
    code path that never configures it."""
    if not settings.sentry_dsn:
        return
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        integrations=[StarletteIntegration(), FastApiIntegration()],
        traces_sample_rate=settings.sentry_traces_sample_rate,
    )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(log_level=settings.log_level)
    _init_sentry_if_configured(settings)

    app = FastAPI(
        title=branding.FULL_NAME,
        description="Institutional-grade agentic natural gas intelligence & paper-trading platform.",
        version="0.1.0",
        lifespan=_lifespan,
    )

    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api = FastAPI(title=f"{branding.FULL_NAME} API")
    for router in (
        auth.router,
        market.router,
        fundamentals.router,
        news.router,
        agents.router,
        trading.router,
        risk.router,
        approvals.router,
        portfolio.router,
        journal.router,
        quant.router,
        chat.router,
        contact.router,
        admin_users.router,
        admin_console.router,
        admin_data_feeds.router,
        admin_agents.router,
        admin_agent_versions.router,
        admin_agent_versions.optimization_router,
        admin_models.router,
        admin_governance.router,
        admin_workspaces.router,
        admin_enterprise_data.router,
        admin_data_governance.router,
        enterprise_webhooks.router,
        alpha.router,
        alpha_enterprise.router,
    ):
        api.include_router(router)

    from .routers import system as system_router

    api.include_router(system_router.router)
    app.mount("/api/v1", api)

    @app.get("/health")
    async def health():
        return {"status": "ok", "product_name": branding.FULL_NAME}

    return app


app = create_app()
