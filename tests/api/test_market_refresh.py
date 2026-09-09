"""`AppState.refresh_market_data` — the fix for prices that were frozen at boot.

Before this existed the market curve was fetched only in `seed()` and on config
Reload, so a long-running deployment served the same Henry Hub number forever
while the UI labelled it live. The worker now calls this on its fast cadence.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def state():
    from api_app import state as state_module

    state_module.reset_app_state()
    yield state_module
    state_module.reset_app_state()


class _StubProvider:
    def __init__(self, drafts=None, error: Exception | None = None):
        self._drafts = drafts or []
        self._error = error
        self.calls = 0

    async def fetch(self, _request):
        self.calls += 1
        if self._error:
            raise self._error
        return list(self._drafts)


def _draft(value: float):
    from datetime import datetime, timezone

    from schemas import DataClassification, Lineage, ObservationDraft

    return ObservationDraft(
        source="TEST", source_type=DataClassification.PUBLIC, series_id="NG.FUT.M1",
        symbol="NG", commodity="NATURAL_GAS", category="PRICE",
        sub_category="FUTURES_SETTLEMENT", geography="US", location="HENRY_HUB",
        value=value, unit="USD_MMBTU",
        observation_time=datetime.now(timezone.utc), publication_time=datetime.now(timezone.utc),
        lineage=Lineage(transform="test"),
    )


@pytest.mark.asyncio
async def test_refresh_updates_both_legs(state):
    app_state = await state.get_app_state()
    app_state.providers.get = lambda pid: {  # type: ignore[method-assign]
        "mock_cme": _StubProvider([_draft(9.99)]),
        "mock_ice": _StubProvider([_draft(20.0)]),
    }[pid]

    result = await app_state.refresh_market_data()

    assert result["market_curve"] == 1
    assert result["ttf"] == 1
    assert app_state.market_curve[0].value == 9.99
    assert app_state.ttf_price[0].value == 20.0


@pytest.mark.asyncio
async def test_an_empty_upstream_keeps_the_last_good_curve(state):
    """A failed fetch must not blank the dashboard — stale-but-labelled beats empty."""
    app_state = await state.get_app_state()
    app_state.market_curve = [_draft(3.21)]

    app_state.providers.get = lambda pid: {  # type: ignore[method-assign]
        "mock_cme": _StubProvider([]),
        "mock_ice": _StubProvider([]),
    }[pid]

    await app_state.refresh_market_data()
    assert app_state.market_curve[0].value == 3.21


@pytest.mark.asyncio
async def test_a_ttf_failure_does_not_stop_the_henry_hub_refresh(state):
    """The two legs are independent; one upstream outage must not take out both."""
    app_state = await state.get_app_state()
    app_state.providers.get = lambda pid: {  # type: ignore[method-assign]
        "mock_cme": _StubProvider([_draft(4.44)]),
        "mock_ice": _StubProvider(error=RuntimeError("ICE down")),
    }[pid]

    result = await app_state.refresh_market_data()

    assert app_state.market_curve[0].value == 4.44
    assert result["market_curve"] == 1
    assert any("ttf" in e for e in result["errors"])


@pytest.mark.asyncio
async def test_refresh_publishes_a_market_price_event(state):
    """This is what makes the dashboard update instantly rather than on reload."""
    app_state = await state.get_app_state()
    app_state.providers.get = lambda pid: {  # type: ignore[method-assign]
        "mock_cme": _StubProvider([_draft(5.55)]),
        "mock_ice": _StubProvider([_draft(21.0)]),
    }[pid]

    seen = []
    original = app_state.event_bus.publish

    async def _capture(event):
        seen.append(event)
        return await original(event)

    app_state.event_bus.publish = _capture  # type: ignore[method-assign]

    await app_state.refresh_market_data()

    published = [e for e in seen if e.event_type.value == "MARKET_PRICE_UPDATED"]
    assert len(published) == 1
    assert published[0].payload["front_month"] == 5.55
    assert published[0].payload["ttf"] == 21.0


@pytest.mark.asyncio
async def test_no_event_published_when_nothing_was_fetched(state):
    """Publishing an update when both legs failed would claim a refresh happened."""
    app_state = await state.get_app_state()
    app_state.providers.get = lambda pid: {  # type: ignore[method-assign]
        "mock_cme": _StubProvider([]),
        "mock_ice": _StubProvider([]),
    }[pid]

    seen = []
    original = app_state.event_bus.publish

    async def _capture(event):
        seen.append(event)
        return await original(event)

    app_state.event_bus.publish = _capture  # type: ignore[method-assign]

    await app_state.refresh_market_data()
    assert not [e for e in seen if e.event_type.value == "MARKET_PRICE_UPDATED"]


@pytest.mark.asyncio
async def test_fast_path_requests_only_the_front_month(state):
    """At a 10s cadence, one HTTP request per curve contract would be thousands of
    upstream calls an hour — the fast path must ask for a single contract."""
    app_state = await state.get_app_state()
    seen = {}

    class _Recording(_StubProvider):
        async def fetch(self, request):
            seen["n_contracts"] = request.extra.get("n_contracts")
            return await super().fetch(request)

    app_state.providers.get = lambda pid: {  # type: ignore[method-assign]
        "mock_cme": _Recording([_draft(6.66)]),
        "mock_ice": _StubProvider([_draft(22.0)]),
    }[pid]

    await app_state.refresh_market_data(full=False)
    assert seen["n_contracts"] == 1

    await app_state.refresh_market_data(full=True)
    assert seen["n_contracts"] is None  # full curve: provider's own default


@pytest.mark.asyncio
async def test_fast_path_splices_the_front_month_and_keeps_deferred_months(state):
    """The chart must not collapse to one point between full refreshes."""
    app_state = await state.get_app_state()
    app_state.market_curve = [_draft(3.00), _draft(3.10), _draft(3.20)]

    app_state.providers.get = lambda pid: {  # type: ignore[method-assign]
        "mock_cme": _StubProvider([_draft(3.55)]),
        "mock_ice": _StubProvider([_draft(20.0)]),
    }[pid]

    await app_state.refresh_market_data(full=False)

    assert [p.value for p in app_state.market_curve] == [3.55, 3.10, 3.20]


@pytest.mark.asyncio
async def test_full_refresh_replaces_the_whole_curve(state):
    app_state = await state.get_app_state()
    app_state.market_curve = [_draft(3.00), _draft(3.10), _draft(3.20)]

    app_state.providers.get = lambda pid: {  # type: ignore[method-assign]
        "mock_cme": _StubProvider([_draft(4.00), _draft(4.10)]),
        "mock_ice": _StubProvider([_draft(20.0)]),
    }[pid]

    await app_state.refresh_market_data(full=True)

    assert [p.value for p in app_state.market_curve] == [4.00, 4.10]
