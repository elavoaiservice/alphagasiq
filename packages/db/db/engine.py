from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool


def build_engine(database_url: str) -> AsyncEngine:
    """Build an async SQLAlchemy engine for `database_url`.

    In-memory SQLite (used by the test suite) needs `StaticPool` so every connection
    shares the same in-process database instead of each getting its own throwaway one
    - otherwise the tables created by `create_all()` vanish between queries.
    """
    if ":memory:" in database_url:
        return create_async_engine(
            database_url,
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
    return create_async_engine(database_url)


def build_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
