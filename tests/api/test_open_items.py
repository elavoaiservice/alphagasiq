"""The remaining open items: scheduler noise, SEC EDGAR identity, fundamentals staleness."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from schemas import DataClassification, Lineage, ObservationDraft


# ── 1. the scheduler must not report inactive providers as failures ───────────

class _Registry:
    def __init__(self, registered):
        self._registered = set(registered)

    def has(self, provider_id):
        return provider_id in self._registered


class _Repo:
    def __init__(self, configs):
        self._configs = configs
        self.events: list[tuple[str, str]] = []

    async def list_data_feed_configs(self):
        return self._configs

    async def mark_data_feed_polled(self, provider_id, when=None):
        pass

    async def record_data_feed_event(self, provider_id, event_type, status, detail, **kw):
        self.events.append((provider_id, status))


class _State:
    def __init__(self, configs, registered):
        self.repo = _Repo(configs)
        self.providers = _Registry(registered)
        self.ingested: list[str] = []

    async def ingest_from_provider(self, provider_id, *, full=True):
        self.ingested.append(provider_id)
        return {"provider_id": provider_id, "records": 1, "applied": "observations", "error": None}


def _cfg(provider_id):
    return {"provider_id": provider_id, "enabled": True, "paused": False,
            "polling_frequency_seconds": 30, "last_polled_at": None}


@pytest.mark.asyncio
async def test_unregistered_providers_are_skipped_not_reported_as_errors():
    """`data_feed_configs` keeps a row per provider ever seen, so turning mocks off
    left mock_cme/mock_ice/mock_news enabled and due. Every tick recorded three
    "not registered" errors — ~250 bogus failures an hour flooding the ingestion log
    and showing the admin Data Feeds page as permanently broken."""
    from api_app import feed_scheduler as fs

    state = _State(
        [_cfg("cme_live"), _cfg("mock_cme"), _cfg("mock_ice"), _cfg("mock_news")],
        registered={"cme_live"},
    )
    result = await fs.poll_due_feeds(state, now=datetime(2026, 9, 16, 12, 0))

    assert state.ingested == ["cme_live"]
    assert result["errors"] == []
    assert sorted(result["not_registered"]) == ["mock_cme", "mock_ice", "mock_news"]
    # And no error event is written for any of them.
    assert [e for e in state.repo.events if e[1] == "error"] == []


# ── 2. SEC EDGAR must not ingest the wrong company ────────────────────────────

def test_every_tracked_cik_is_ten_digits():
    from data_service.providers.sec_edgar import TRACKED_COMPANIES

    for cik in TRACKED_COMPANIES:
        assert len(cik) == 10 and cik.isdigit(), cik


def test_name_matching_accepts_sec_formatting_variants():
    from data_service.providers.sec_edgar import _names_match

    assert _names_match("Williams Companies, Inc.", "WILLIAMS COMPANIES, INC.")
    assert _names_match("EQT Corp", "EQT Corporation")
    assert _names_match("ONEOK, Inc.", "ONEOK INC /NEW/")


def test_name_matching_rejects_a_different_company():
    """The dangerous case: a valid CIK for the wrong company returns 200, and its
    filings flow in under the label we expected. Two of the four original CIKs did
    exactly this — Williams resolved to Norwegian Cruise Line, Kinder Morgan to a
    biotech."""
    from data_service.providers.sec_edgar import _names_match

    assert not _names_match("Williams Companies, Inc.", "Norwegian Cruise Line Holdings Ltd.")
    assert not _names_match("Kinder Morgan, Inc.", "Aravive, Inc.")


@pytest.mark.asyncio
async def test_fetch_refuses_filings_from_a_mismatched_company():
    import httpx

    from data_sdk import FetchRequest
    from data_service.providers.sec_edgar import SECEdgarProvider

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "name": "Norwegian Cruise Line Holdings Ltd.",
            "filings": {"recent": {"form": ["8-K"], "filingDate": ["2026-09-01"],
                                   "accessionNumber": ["0001-26-000001"],
                                   "primaryDocument": ["a.htm"]}},
        })

    provider = SECEdgarProvider(
        contact_email="t@example.com",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    drafts = await provider.fetch(FetchRequest(extra={"ciks": ["0000107263"]}))
    assert drafts == []


@pytest.mark.asyncio
async def test_one_failing_cik_does_not_abort_the_batch():
    import httpx

    from data_sdk import FetchRequest
    from data_service.providers.sec_edgar import SECEdgarProvider

    def handler(request: httpx.Request) -> httpx.Response:
        if "0000033213" in str(request.url):
            return httpx.Response(200, json={
                "name": "EQT Corp",
                "filings": {"recent": {"form": ["8-K"], "filingDate": ["2026-09-01"],
                                       "accessionNumber": ["0001-26-000001"],
                                       "primaryDocument": ["a.htm"]}},
            })
        return httpx.Response(404)

    provider = SECEdgarProvider(
        contact_email="t@example.com",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    drafts = await provider.fetch(FetchRequest(extra={"ciks": ["0000000001", "0000033213"]}))
    assert len(drafts) == 1


# ── 3. fundamentals must not stay at the API's boot values ────────────────────

@pytest.fixture
def state_module():
    from api_app import state as sm

    sm.reset_app_state()
    yield sm
    sm.reset_app_state()


def _storage_draft(value: float, when: datetime):
    return ObservationDraft(
        source="EIA", source_type=DataClassification.PUBLIC,
        series_id="EIA.NG.STORAGE.LOWER48", commodity="NATURAL_GAS",
        category="FUNDAMENTALS", sub_category="STORAGE", geography="US",
        value=value, unit="BCF", observation_time=when, publication_time=when,
        lineage=Lineage(transform="test"),
    )


@pytest.mark.asyncio
async def test_storage_baseline_is_rederived_from_persisted_history(state_module):
    """The worker derives the baseline and holds it in *its* memory; the API's copy
    stayed at boot. Both read the same persisted EIA history."""
    app_state = await state_module.get_app_state()
    async with app_state.repo.engine.begin() as conn:
        await conn.execute(text("DELETE FROM alpha_market_observations"))

    base = datetime(2026, 9, 16, tzinfo=timezone.utc)
    await app_state._persist_market_observations([
        _storage_draft(3000 + i * 10, base - timedelta(weeks=i)) for i in range(60)
    ])

    result = await app_state.rehydrate_fundamentals_from_db()

    assert result["storage_updated"] is True
    assert app_state.storage_baseline_classification == "PUBLIC"


@pytest.mark.asyncio
async def test_rehydrate_fundamentals_never_raises_on_a_db_error(state_module):
    app_state = await state_module.get_app_state()

    async def _boom(**kwargs):
        raise RuntimeError("db down")

    app_state.repo.list_market_observations_as_of = _boom  # type: ignore[method-assign]
    app_state.repo.latest_observation_per_series = _boom  # type: ignore[method-assign]

    result = await app_state.rehydrate_fundamentals_from_db()
    assert len(result["errors"]) == 2


@pytest.mark.asyncio
async def test_insufficient_history_leaves_the_baseline_untouched(state_module):
    """Better a boot-time baseline than one derived from a single print."""
    app_state = await state_module.get_app_state()
    async with app_state.repo.engine.begin() as conn:
        await conn.execute(text("DELETE FROM alpha_market_observations"))
    before = dict(app_state.storage_baseline)

    await app_state._persist_market_observations(
        [_storage_draft(3000, datetime(2026, 9, 16, tzinfo=timezone.utc))]
    )
    result = await app_state.rehydrate_fundamentals_from_db()

    assert result["storage_updated"] is False
    assert app_state.storage_baseline == before
