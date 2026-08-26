from __future__ import annotations

from contextlib import asynccontextmanager

from config import branding, get_settings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import (
    admin_users,
    agents,
    approvals,
    auth,
    chat,
    contact,
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


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=branding.FULL_NAME,
        description="Institutional-grade agentic natural gas intelligence & paper-trading platform.",
        version="0.1.0",
        lifespan=_lifespan,
    )

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
