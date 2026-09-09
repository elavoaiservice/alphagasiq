"""Per-feed polling (`api_app/feed_scheduler.py`).

Before this, `polling_frequency_seconds`, `enabled` and `paused` were editable in
the admin Data Feeds page but read by nothing — ingestion was hardcoded. These
tests pin the behaviour that makes those controls real.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from api_app import feed_scheduler as fs


def _config(provider_id="eia", **kw):
    base = {
        "provider_id": provider_id,
        "enabled": True,
        "paused": False,
        "polling_frequency_seconds": None,
        "last_polled_at": None,
    }
    base.update(kw)
    return base


NOW = datetime(2026, 9, 9, 12, 0, 0)


# ── the interval actually in force ────────────────────────────────────────────

def test_configured_frequency_wins_over_the_default():
    assert fs.effective_interval("eia", 45) == 45


def test_null_frequency_falls_back_to_the_provider_default_not_never():
    """A blank field must not silently disable a feed."""
    assert fs.effective_interval("eia", None) == fs.DEFAULT_POLL_SECONDS["eia"]


def test_zero_or_negative_frequency_falls_back_to_the_default():
    assert fs.effective_interval("eia", 0) == fs.DEFAULT_POLL_SECONDS["eia"]
    assert fs.effective_interval("eia", -5) == fs.DEFAULT_POLL_SECONDS["eia"]


def test_a_provider_with_no_default_is_not_scheduled():
    """The honest stubs (ferc_public, pipeline_bulletin_board, …) have nothing to
    fetch, so they must never be polled."""
    assert fs.effective_interval("ferc_public", None) is None


def test_an_unscheduled_provider_can_still_be_polled_if_explicitly_configured():
    assert fs.effective_interval("ferc_public", 600) == 600


# ── due-ness ──────────────────────────────────────────────────────────────────

def test_a_never_polled_feed_is_due_immediately():
    """Otherwise a newly-registered feed waits a full interval before its first poll."""
    assert fs.is_due(_config(last_polled_at=None), NOW) is True


def test_a_feed_is_not_due_before_its_interval_elapses():
    cfg = _config(polling_frequency_seconds=600, last_polled_at=NOW - timedelta(seconds=599))
    assert fs.is_due(cfg, NOW) is False


def test_a_feed_is_due_once_its_interval_elapses():
    cfg = _config(polling_frequency_seconds=600, last_polled_at=NOW - timedelta(seconds=600))
    assert fs.is_due(cfg, NOW) is True


def test_a_disabled_feed_is_never_due():
    cfg = _config(enabled=False, last_polled_at=None)
    assert fs.is_due(cfg, NOW) is False


def test_a_paused_feed_is_never_due():
    cfg = _config(paused=True, last_polled_at=None)
    assert fs.is_due(cfg, NOW) is False


def test_an_unscheduled_provider_is_never_due():
    assert fs.is_due(_config("ferc_public"), NOW) is False


# ── next-due reporting for the admin page ─────────────────────────────────────

def test_next_due_is_last_poll_plus_the_interval():
    cfg = _config(polling_frequency_seconds=300, last_polled_at=NOW)
    assert fs.next_due_at(cfg) == NOW + timedelta(seconds=300)


def test_next_due_is_none_for_a_paused_or_disabled_feed():
    assert fs.next_due_at(_config(paused=True, last_polled_at=NOW)) is None
    assert fs.next_due_at(_config(enabled=False, last_polled_at=NOW)) is None


# ── advisory ──────────────────────────────────────────────────────────────────

def test_advisory_warns_when_polling_far_faster_than_the_upstream_publishes():
    note = fs.advisory_for("eia", 10)
    assert note is not None and "same data" in note


def test_no_advisory_for_a_sensible_frequency():
    assert fs.advisory_for("eia", 3600) is None


def test_advisory_explains_the_delay_on_the_free_market_quotes():
    note = fs.advisory_for("cme_live", 5)
    assert note is not None and "delayed" in note


def test_no_advisory_when_the_operator_left_it_unset():
    assert fs.advisory_for("eia", None) is None


# ── the poll cycle ────────────────────────────────────────────────────────────

class _Repo:
    def __init__(self, configs):
        self._configs = configs
        self.polled: list[str] = []
        self.events: list[tuple[str, str]] = []

    async def list_data_feed_configs(self):
        return self._configs

    async def mark_data_feed_polled(self, provider_id, when=None):
        self.polled.append(provider_id)

    async def record_data_feed_event(self, provider_id, event_type, status, detail, records_received=None, **kw):
        self.events.append((provider_id, status))


class _State:
    def __init__(self, configs, results=None):
        self.repo = _Repo(configs)
        self.ingested: list[tuple[str, bool]] = []
        self._results = results or {}

    async def ingest_from_provider(self, provider_id, *, full=True):
        self.ingested.append((provider_id, full))
        return self._results.get(
            provider_id, {"provider_id": provider_id, "records": 3, "applied": "observations", "error": None}
        )


@pytest.mark.asyncio
async def test_only_due_feeds_are_ingested():
    state = _State([
        _config("eia", polling_frequency_seconds=600, last_polled_at=NOW - timedelta(seconds=601)),
        _config("noaa_nws", polling_frequency_seconds=600, last_polled_at=NOW - timedelta(seconds=10)),
        _config("nhc_tropical", paused=True),
    ])
    result = await fs.poll_due_feeds(state, now=NOW)

    assert [p for p, _ in state.ingested] == ["eia"]
    assert result["skipped"] == 2
    assert result["polled"][0]["provider_id"] == "eia"


@pytest.mark.asyncio
async def test_the_curve_is_fetched_partially_on_a_scheduled_poll():
    """A full curve is one request per contract; a short interval would be thousands
    of upstream requests an hour."""
    state = _State([_config("cme_live")])
    await fs.poll_due_feeds(state, now=NOW)
    assert state.ingested == [("cme_live", False)]


@pytest.mark.asyncio
async def test_other_feeds_are_fetched_in_full():
    state = _State([_config("noaa_nws")])
    await fs.poll_due_feeds(state, now=NOW)
    assert state.ingested == [("noaa_nws", True)]


@pytest.mark.asyncio
async def test_one_failing_feed_does_not_stop_the_others():
    state = _State(
        [_config("eia"), _config("noaa_nws")],
        results={"eia": {"provider_id": "eia", "records": 0, "applied": None, "error": "boom"}},
    )
    result = await fs.poll_due_feeds(state, now=NOW)

    assert [p for p, _ in state.ingested] == ["eia", "noaa_nws"]
    assert any("eia" in e for e in result["errors"])
    assert [p["provider_id"] for p in result["polled"]] == ["noaa_nws"]


@pytest.mark.asyncio
async def test_a_failing_feed_is_still_stamped_so_it_is_not_retried_every_tick():
    """Retrying a down upstream on every tick would hammer a struggling provider."""
    state = _State(
        [_config("eia")],
        results={"eia": {"provider_id": "eia", "records": 0, "applied": None, "error": "boom"}},
    )
    await fs.poll_due_feeds(state, now=NOW)
    assert state.repo.polled == ["eia"]
    assert state.repo.events == [("eia", "error")]


@pytest.mark.asyncio
async def test_a_config_read_failure_returns_an_error_not_an_exception():
    class _Broken(_State):
        async def _boom(self):
            raise RuntimeError("db down")

    state = _State([])

    async def _raise():
        raise RuntimeError("db down")

    state.repo.list_data_feed_configs = _raise  # type: ignore[method-assign]
    result = await fs.poll_due_feeds(state, now=NOW)
    assert result["errors"] and "config read failed" in result["errors"][0]
