"""`AppState.rehydrate_market_from_db` — the stale-dashboard fix.

The API and the worker are separate processes with separate `AppState` objects.
The worker fetched prices and persisted them; the API only ever fetched at its
own boot. In production that meant `GET /market/curve/front-month` served an
`as_of` of 01:55 with $2.934 while the database held 12:38 and $2.969 — real
data, more than ten hours stale on screen.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sqlalchemy import text

from schemas import DataClassification, Lineage, ObservationDraft


async def _clear_observations(app_state) -> None:
    """`get_app_state()` seeds a full MOCK_CME curve, which would outrank any test
    data written with an earlier timestamp. These tests own the store outright."""
    async with app_state.repo.engine.begin() as conn:
        await conn.execute(text("DELETE FROM alpha_market_observations"))


@pytest.fixture
def state_module():
    from api_app import state as sm

    sm.reset_app_state()
    yield sm
    sm.reset_app_state()


def _curve_draft(value: float, position: int, when: datetime, symbol="NGU26"):
    return ObservationDraft(
        source="YAHOO_NYMEX", source_type=DataClassification.PUBLIC,
        series_id=f"NG.FUT.M{position}", symbol=symbol, commodity="NATURAL_GAS",
        category="PRICE", sub_category="FUTURES_SETTLEMENT", geography="US",
        location="HENRY_HUB", value=value, unit="USD_MMBTU",
        observation_time=when, publication_time=when,
        metadata={"curve_position": f"M{position}"},
        lineage=Lineage(transform="test"),
    )


def _ttf_draft(value: float, when: datetime):
    return ObservationDraft(
        source="YAHOO_ICE", source_type=DataClassification.PUBLIC,
        series_id="TTF.FRONT_MONTH", symbol="TTF", commodity="NATURAL_GAS",
        category="PRICE", sub_category="FUTURES_SETTLEMENT", geography="EU",
        location="TTF", value=value, unit="USD_MMBTU",
        observation_time=when, publication_time=when,
        lineage=Lineage(transform="test"),
    )


@pytest.mark.asyncio
async def test_rehydrate_replaces_a_stale_in_memory_curve(state_module):
    """The production bug, reproduced: memory holds boot prices, the DB holds newer
    ones written by the other process."""
    app_state = await state_module.get_app_state()
    await _clear_observations(app_state)
    boot = datetime(2026, 9, 16, 1, 55, tzinfo=timezone.utc)
    later = datetime(2026, 9, 16, 12, 38, tzinfo=timezone.utc)

    app_state.market_curve = [_curve_draft(2.934, 1, boot)]
    await app_state._persist_market_observations([_curve_draft(2.969, 1, later)])

    result = await app_state.rehydrate_market_from_db()

    assert result["market_curve"] == 1
    assert app_state.market_curve[0].value == 2.969


@pytest.mark.asyncio
async def test_rehydrate_orders_the_curve_by_contract_not_by_time(state_module):
    """`market_curve[0]` is relied on everywhere to be the front month —
    `primary_instrument()`, `mark_price()`, trade entry prices."""
    app_state = await state_module.get_app_state()
    await _clear_observations(app_state)
    now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)

    # Persisted out of order, and M2 written most recently.
    await app_state._persist_market_observations([
        _curve_draft(3.10, 3, now - timedelta(seconds=2)),
        _curve_draft(2.90, 1, now - timedelta(seconds=1)),
        _curve_draft(3.00, 2, now),
    ])

    await app_state.rehydrate_market_from_db()

    assert [d.metadata["curve_position"] for d in app_state.market_curve] == ["M1", "M2", "M3"]
    assert app_state.market_curve[0].value == 2.90


@pytest.mark.asyncio
async def test_rehydrate_reloads_ttf(state_module):
    app_state = await state_module.get_app_state()
    await _clear_observations(app_state)
    now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    app_state.ttf_price = [_ttf_draft(9.50, now - timedelta(hours=10))]
    await app_state._persist_market_observations([_ttf_draft(27.385, now)])

    await app_state.rehydrate_market_from_db()

    assert app_state.ttf_price[0].value == 27.385


@pytest.mark.asyncio
async def test_an_empty_database_keeps_the_in_memory_curve(state_module):
    """A fresh install must not have its seeded curve blanked by an empty store."""
    app_state = await state_module.get_app_state()
    await _clear_observations(app_state)
    now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    app_state.market_curve = [_curve_draft(3.33, 1, now)]

    result = await app_state.rehydrate_market_from_db()

    assert app_state.market_curve[0].value == 3.33
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_rehydrate_publishes_only_when_the_price_changed(state_module):
    """The API owns the WebSocket, so re-publishing what it observes is what makes
    the browser update — the worker's own events never cross the process boundary
    with the default in-memory bus. But publishing every cycle would spam clients."""
    app_state = await state_module.get_app_state()
    await _clear_observations(app_state)
    now = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    await app_state._persist_market_observations([_curve_draft(2.50, 1, now)])

    seen = []
    original = app_state.event_bus.publish

    async def _capture(event):
        seen.append(event.event_type.value)
        return await original(event)

    app_state.event_bus.publish = _capture  # type: ignore[method-assign]

    first = await app_state.rehydrate_market_from_db()
    seen.clear()
    second = await app_state.rehydrate_market_from_db()  # nothing new in the DB

    assert first["changed"] is True
    assert second["changed"] is False
    assert "MARKET_PRICE_UPDATED" not in seen, "an unchanged cycle must not publish"


@pytest.mark.asyncio
async def test_rehydrate_never_raises_on_a_database_error(state_module):
    """A transient DB error must not kill the loop and freeze the dashboard for the
    life of the process."""
    app_state = await state_module.get_app_state()

    async def _boom(**kwargs):
        raise RuntimeError("db down")

    app_state.repo.latest_observation_per_series = _boom  # type: ignore[method-assign]

    result = await app_state.rehydrate_market_from_db()
    assert result["errors"]
