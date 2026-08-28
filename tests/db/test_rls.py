"""Postgres Row Level Security (`db.rls`, docs/alpha-intelligence.md section
11.1): a real database-level backstop layered on top of Milestone 9's
application-layer cross-organization data-visibility fix.

Pure unit tests (statement generation, GUC value resolution, SQLite no-ops)
run everywhere. The live-Postgres integration tests below prove the actual
enforcement -- not just that the SQL text looks right -- against a real
local Postgres instance; they skip gracefully (`_HAS_POSTGRES`) when none is
reachable, since SQLite (every default dev/test database) has no RLS
equivalent at all and CI does not run a Postgres service for this repo yet.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from db import SqlAppRepository
from db.rls import ORG_SCOPED_TABLES, PLATFORM_ONLY_SENTINEL, build_row_level_security_statements, resolve_org_guc_value
from schemas import Signal, SignalDirection, SignalStatus, SignalType
from sqlalchemy import text

_TEST_POSTGRES_URL = "postgresql+asyncpg://alphagasiq_test:alphagasiq_test@127.0.0.1:5432/alphagasiq_test"


def _postgres_reachable() -> bool:
    async def _check() -> bool:
        repo = SqlAppRepository(_TEST_POSTGRES_URL)
        try:
            async with repo.engine.connect():
                return True
        except Exception:
            return False
        finally:
            await repo.dispose()

    try:
        return asyncio.run(_check())
    except Exception:
        return False


_HAS_POSTGRES = _postgres_reachable()


# -- pure: statement generation ----------------------------------------------


def test_build_row_level_security_statements_covers_every_org_scoped_table():
    statements = build_row_level_security_statements()
    for table in ORG_SCOPED_TABLES:
        assert any(f'"{table}"' in s and "FORCE ROW LEVEL SECURITY" in s for s in statements), table
        assert any(f'"{table}"' in s and s.startswith("CREATE POLICY") for s in statements), table
        assert any(f'"{table}"' in s and s.startswith("DROP POLICY IF EXISTS") for s in statements), table


def test_build_row_level_security_statements_policy_shape():
    statements = build_row_level_security_statements(("alpha_signals",))
    policy = next(s for s in statements if s.startswith("CREATE POLICY"))
    assert PLATFORM_ONLY_SENTINEL in policy
    assert "organization_id" in policy
    assert "current_setting('app.current_org_id', true)" in policy


def test_resolve_org_guc_value_precedence():
    assert resolve_org_guc_value(organization_id="org-1", platform_only=True) == "org-1"
    assert resolve_org_guc_value(organization_id="org-1", platform_only=False) == "org-1"
    assert resolve_org_guc_value(organization_id=None, platform_only=True) == PLATFORM_ONLY_SENTINEL
    assert resolve_org_guc_value(organization_id=None, platform_only=False) == ""


# -- pure: SQLite (the default dev/test DB) stays a documented no-op --------


async def test_apply_row_level_security_is_a_noop_on_sqlite():
    repo = SqlAppRepository("sqlite+aiosqlite:///:memory:")
    await repo.init_schema()
    await repo.apply_row_level_security()  # must not raise
    await repo.dispose()


async def test_set_org_guc_is_a_noop_on_sqlite():
    repo = SqlAppRepository("sqlite+aiosqlite:///:memory:")
    await repo.init_schema()
    async with repo.session_factory() as session:
        await repo._set_org_guc(session, organization_id="org-1", platform_only=False)  # must not raise
    await repo.dispose()


def _signal(organization_id: str | None, headline: str) -> Signal:
    return Signal(
        organization_id=organization_id,
        signal_type=SignalType.PRICE_MOVE,
        category="MARKET",
        headline=headline,
        description=headline,
        materiality_score=90.0,
        novelty_score=50.0,
        confidence=0.9,
        direction=SignalDirection.BULLISH,
        status=SignalStatus.ACTIVE,
    )


@pytest.mark.skipif(not _HAS_POSTGRES, reason="no local Postgres reachable at 127.0.0.1:5432")
class TestLivePostgresRowLevelSecurity:
    """Runs against a real local Postgres 16 instance -- proves RLS actually
    restricts rows, not merely that the migration's SQL text parses."""

    async def _repo(self) -> SqlAppRepository:
        repo = SqlAppRepository(_TEST_POSTGRES_URL)
        await repo.init_schema()
        await repo.apply_row_level_security()
        return repo

    async def test_rls_agrees_with_and_backstops_the_application_layer_filter(self):
        repo = await self._repo()
        try:
            token = uuid.uuid4().hex[:8]
            org_a = (await repo.create_organization(name=f"RLS Test Org A {token}"))["id"]
            org_b = (await repo.create_organization(name=f"RLS Test Org B {token}"))["id"]
            headline_a, headline_b, headline_platform = f"{token} org A signal", f"{token} org B signal", f"{token} platform signal"
            await repo.save_signal(_signal(org_a, headline_a))
            await repo.save_signal(_signal(org_b, headline_b))
            await repo.save_signal(_signal(None, headline_platform))

            def _headlines(rows: list[dict]) -> set[str]:
                return {s["headline"] for s in rows if token in s["headline"]}

            org_a_headlines = _headlines(await repo.list_signals(organization_id=org_a, limit=200))
            assert org_a_headlines == {headline_a, headline_platform}

            platform_headlines = _headlines(await repo.list_signals(platform_only=True, limit=200))
            assert platform_headlines == {headline_platform}

            # Unrestricted (today's default, GUC unset) still sees everything -- no regression.
            unrestricted_headlines = _headlines(await repo.list_signals(limit=200))
            assert unrestricted_headlines == {headline_a, headline_b, headline_platform}
        finally:
            await repo.dispose()

    async def test_rls_blocks_a_raw_query_that_never_calls_the_application_filter(self):
        """The actual point of a database-level backstop: even a hand-written
        query that forgets `organization_id`/`platform_only` filtering
        entirely still cannot see another organization's row once the
        session GUC is set -- RLS enforces it independently of application
        code correctness."""
        repo = await self._repo()
        try:
            token = uuid.uuid4().hex[:8]
            org_a = (await repo.create_organization(name=f"RLS Raw Test Org A {token}"))["id"]
            org_b = (await repo.create_organization(name=f"RLS Raw Test Org B {token}"))["id"]
            headline_a, headline_b = f"{token} org A raw", f"{token} org B raw"
            await repo.save_signal(_signal(org_a, headline_a))
            await repo.save_signal(_signal(org_b, headline_b))

            async with repo.session_factory() as session:
                await repo._set_org_guc(session, organization_id=org_a, platform_only=False)
                result = await session.execute(
                    text("SELECT headline FROM alpha_signals WHERE headline IN (:a, :b)"),
                    {"a": headline_a, "b": headline_b},
                )
                headlines = {row[0] for row in result}
            assert headlines == {headline_a}
        finally:
            await repo.dispose()

    async def test_apply_row_level_security_is_idempotent(self):
        repo = await self._repo()
        try:
            await repo.apply_row_level_security()  # re-running must not raise
        finally:
            await repo.dispose()
