"""`create_all` cannot add a column to an existing table.

This is not theoretical: `data_feed_configs.last_polled_at` shipped and was simply
absent in the deployed database, so every `SELECT` of the model raised
`ProgrammingError` and the whole feed scheduler went offline — 130 consecutive
`config read failed` cycles — while the `deploy_log` *table* in the same release was
created fine. `init_schema` now backfills missing additive columns.
"""
from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

from db.models import Base
from db.repository import SqlAppRepository, _add_missing_columns


@pytest.mark.asyncio
async def test_a_missing_column_is_added_to_an_existing_table():
    repo = SqlAppRepository("sqlite+aiosqlite:///:memory:")
    await repo.init_schema()

    # Simulate the deployed state: the table exists but predates the new column.
    async with repo.engine.begin() as conn:
        await conn.execute(text("ALTER TABLE data_feed_configs DROP COLUMN last_polled_at"))
        cols = await conn.run_sync(lambda c: {x["name"] for x in inspect(c).get_columns("data_feed_configs")})
        assert "last_polled_at" not in cols

    # create_all alone must NOT fix it — that is the bug being guarded against.
    async with repo.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        cols = await conn.run_sync(lambda c: {x["name"] for x in inspect(c).get_columns("data_feed_configs")})
        assert "last_polled_at" not in cols, "create_all is not expected to alter existing tables"

    # The backfill does.
    async with repo.engine.begin() as conn:
        await conn.run_sync(_add_missing_columns)
        cols = await conn.run_sync(lambda c: {x["name"] for x in inspect(c).get_columns("data_feed_configs")})
    assert "last_polled_at" in cols

    await repo.dispose()


@pytest.mark.asyncio
async def test_the_repaired_column_is_actually_usable():
    """Adding the column is only half of it — the model must round-trip through it,
    which is what the scheduler needs."""
    repo = SqlAppRepository("sqlite+aiosqlite:///:memory:")
    await repo.init_schema()
    async with repo.engine.begin() as conn:
        await conn.execute(text("ALTER TABLE data_feed_configs DROP COLUMN last_polled_at"))
    await repo.init_schema()  # re-run: create_all + backfill

    await repo.seed_data_feed_configs(["eia"])
    await repo.mark_data_feed_polled("eia")
    configs = await repo.list_data_feed_configs()

    assert configs[0]["last_polled_at"] is not None
    await repo.dispose()


@pytest.mark.asyncio
async def test_init_schema_is_idempotent():
    repo = SqlAppRepository("sqlite+aiosqlite:///:memory:")
    await repo.init_schema()
    await repo.init_schema()
    await repo.init_schema()

    async with repo.engine.begin() as conn:
        cols = await conn.run_sync(lambda c: [x["name"] for x in inspect(c).get_columns("data_feed_configs")])
    assert len(cols) == len(set(cols)), "a column must not be added twice"
    await repo.dispose()
