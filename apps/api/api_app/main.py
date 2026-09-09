from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime

from config import Settings, branding, get_settings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .logging_config import RequestLoggingMiddleware, configure_logging
from .routers import (
    admin_agent_versions,
    admin_agents,
    admin_config,
    admin_console,
    admin_data_feeds,
    admin_data_governance,
    admin_enterprise_data,
    admin_governance,
    admin_models,
    admin_token_usage,
    admin_changelog,
    admin_upgrade,
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
    ws,
)
from .state import get_app_state


@asynccontextmanager
async def _lifespan(app: FastAPI):
    state = await get_app_state()
    # Apply GUI-managed config overlay (DB → os.environ) + rebuild the data
    # provider registry so entered settings take effect on boot. Best-effort:
    # never block startup if the config table isn't ready yet.
    try:
        from . import config_store
        await config_store.reload_runtime(state)
    except Exception:  # noqa: BLE001
        pass
    # Record that this build is now serving, so the admin Changelog can say when
    # each change went live rather than only when it was committed. Idempotent
    # per commit sha, so a restart is not logged as a new release. Best-effort:
    # a deploy-log failure must never stop the API from booting.
    try:
        from .version import build_info

        info = build_info()
        if info.get("commit"):
            built_at = None
            raw_built = info.get("built_at")
            if raw_built:
                try:
                    built_at = datetime.fromisoformat(raw_built).replace(tzinfo=None)
                except ValueError:
                    built_at = None
            await state.repo.record_deploy(
                commit_sha=info["commit"],
                environment=get_settings().environment,
                branch=info.get("branch"),
                subject=info.get("subject"),
                built_at=built_at,
            )
    except Exception:  # noqa: BLE001
        pass
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
        admin_config.router,
        admin_token_usage.router,
        admin_changelog.router,
        admin_upgrade.router,
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
        ws.router,
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
