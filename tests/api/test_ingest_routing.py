"""`AppState.ingest_from_provider` — fetching a feed AND applying its data.

These two were previously separate: the admin manual-refresh button called
`provider.fetch()` and discarded the result, reporting success while nothing
changed. Every assertion here is about the data actually landing somewhere.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from schemas import DataClassification, Lineage, ObservationDraft


@pytest.fixture
def state_module():
    from api_app import state as sm

    sm.reset_app_state()
    yield sm
    sm.reset_app_state()


def _draft(value: float, series_id="NG.FUT.M1", location="HENRY_HUB"):
    now = datetime.now(timezone.utc)
    return ObservationDraft(
        source="TEST", source_type=DataClassification.PUBLIC, series_id=series_id,
        symbol="NG", commodity="NATURAL_GAS", category="PRICE",
        sub_category="FUTURES_SETTLEMENT", geography="US", location=location,
        value=value, unit="USD_MMBTU", observation_time=now, publication_time=now,
        lineage=Lineage(transform="test"),
    )


class _Stub:
    def __init__(self, drafts=None, error=None):
        self._drafts = drafts if drafts is not None else []
        self._error = error
        self.requests = []

    async def fetch(self, request):
        self.requests.append(request)
        if self._error:
            raise self._error
        return list(self._drafts)


def _wire(app_state, mapping):
    app_state.providers.get = lambda pid: mapping.get(pid)  # type: ignore[method-assign]


@pytest.mark.asyncio
async def test_market_provider_updates_the_curve(state_module):
    app_state = await state_module.get_app_state()
    _wire(app_state, {"mock_cme": _Stub([_draft(7.77), _draft(7.88)])})

    summary = await app_state.ingest_from_provider("mock_cme")

    assert summary["applied"] == "market_curve"
    assert summary["records"] == 2
    assert app_state.market_curve[0].value == 7.77


@pytest.mark.asyncio
async def test_ttf_provider_updates_the_ttf_price(state_module):
    app_state = await state_module.get_app_state()
    _wire(app_state, {"mock_ice": _Stub([_draft(25.5, series_id="TTF.FRONT_MONTH", location="TTF")])})

    summary = await app_state.ingest_from_provider("mock_ice")

    assert summary["applied"] == "ttf_price"
    assert app_state.ttf_price[0].value == 25.5


@pytest.mark.asyncio
async def test_partial_market_fetch_requests_one_contract_and_splices(state_module):
    app_state = await state_module.get_app_state()
    app_state.market_curve = [_draft(3.0), _draft(3.1), _draft(3.2)]
    stub = _Stub([_draft(3.9)])
    _wire(app_state, {"mock_cme": stub})

    await app_state.ingest_from_provider("mock_cme", full=False)

    assert stub.requests[0].extra.get("n_contracts") == 1
    assert [p.value for p in app_state.market_curve] == [3.9, 3.1, 3.2]


@pytest.mark.asyncio
async def test_an_empty_result_never_overwrites_good_state(state_module):
    """An upstream outage is not new data."""
    app_state = await state_module.get_app_state()
    app_state.market_curve = [_draft(4.4)]
    _wire(app_state, {"mock_cme": _Stub([])})

    summary = await app_state.ingest_from_provider("mock_cme")

    assert summary["applied"] == "none (empty result)"
    assert app_state.market_curve[0].value == 4.4


@pytest.mark.asyncio
async def test_a_fetch_failure_is_reported_not_raised(state_module):
    app_state = await state_module.get_app_state()
    _wire(app_state, {"mock_cme": _Stub(error=RuntimeError("upstream down"))})

    summary = await app_state.ingest_from_provider("mock_cme")

    assert summary["error"] and "upstream down" in summary["error"]
    assert summary["records"] == 0


@pytest.mark.asyncio
async def test_an_unregistered_provider_is_reported_not_raised(state_module):
    app_state = await state_module.get_app_state()
    _wire(app_state, {})

    summary = await app_state.ingest_from_provider("nope")
    assert summary["error"] == "not registered"


@pytest.mark.asyncio
async def test_an_unmapped_provider_still_persists_its_observations(state_module):
    """NHC/ISO-RTO/EDGAR have no derived engine input yet, but persisting them is
    real ingestion, not a no-op."""
    app_state = await state_module.get_app_state()
    _wire(app_state, {"nhc_tropical": _Stub([_draft(1.0, series_id="NHC.STORM")])})

    summary = await app_state.ingest_from_provider("nhc_tropical")
    assert summary["applied"] == "observations"
    assert summary["records"] == 1


@pytest.mark.asyncio
async def test_market_ingest_publishes_a_price_event(state_module):
    app_state = await state_module.get_app_state()
    _wire(app_state, {"mock_cme": _Stub([_draft(8.88)])})

    seen = []
    original = app_state.event_bus.publish

    async def _capture(event):
        seen.append(event)
        return await original(event)

    app_state.event_bus.publish = _capture  # type: ignore[method-assign]

    await app_state.ingest_from_provider("mock_cme")

    assert [e for e in seen if e.event_type.value == "MARKET_PRICE_UPDATED"]
