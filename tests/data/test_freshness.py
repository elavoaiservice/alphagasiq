"""Phase 1 free-data-feed integration (docs/data-sources.md): the freshness state
machine (`data_sdk.compute_freshness_status`) -- derives LIVE/CURRENT/DELAYED/STALE/
FAILED/UNKNOWN from how old the latest observation is relative to the provider's
expected update cadence, never from "the API call succeeded" alone."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from data_sdk import compute_freshness_status

_NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
_WEEKLY = 7 * 24 * 3600


def test_unavailable_connection_is_failed():
    status = compute_freshness_status(
        connection_status="unavailable",
        last_observation_time=_NOW,
        expected_update_frequency_seconds=_WEEKLY,
        now=_NOW,
    )
    assert status == "FAILED"


def test_not_configured_is_unknown():
    status = compute_freshness_status(
        connection_status="not_configured",
        last_observation_time=None,
        expected_update_frequency_seconds=_WEEKLY,
        now=_NOW,
    )
    assert status == "UNKNOWN"


def test_no_observation_yet_is_unknown():
    status = compute_freshness_status(
        connection_status="healthy",
        last_observation_time=None,
        expected_update_frequency_seconds=_WEEKLY,
        now=_NOW,
    )
    assert status == "UNKNOWN"


def test_no_expected_frequency_is_unknown():
    status = compute_freshness_status(
        connection_status="healthy",
        last_observation_time=_NOW,
        expected_update_frequency_seconds=None,
        now=_NOW,
    )
    assert status == "UNKNOWN"


def test_very_recent_observation_is_live():
    status = compute_freshness_status(
        connection_status="healthy",
        last_observation_time=_NOW - timedelta(minutes=1),
        expected_update_frequency_seconds=_WEEKLY,
        now=_NOW,
    )
    assert status == "LIVE"


def test_observation_within_cadence_is_current():
    status = compute_freshness_status(
        connection_status="healthy",
        last_observation_time=_NOW - timedelta(days=3),
        expected_update_frequency_seconds=_WEEKLY,
        now=_NOW,
    )
    assert status == "CURRENT"


def test_observation_within_2x_cadence_is_delayed():
    status = compute_freshness_status(
        connection_status="healthy",
        last_observation_time=_NOW - timedelta(days=10),
        expected_update_frequency_seconds=_WEEKLY,
        now=_NOW,
    )
    assert status == "DELAYED"


def test_observation_beyond_2x_cadence_is_stale():
    status = compute_freshness_status(
        connection_status="healthy",
        last_observation_time=_NOW - timedelta(days=30),
        expected_update_frequency_seconds=_WEEKLY,
        now=_NOW,
    )
    assert status == "STALE"


def test_future_dated_observation_is_unknown_not_live():
    status = compute_freshness_status(
        connection_status="healthy",
        last_observation_time=_NOW + timedelta(days=1),
        expected_update_frequency_seconds=_WEEKLY,
        now=_NOW,
    )
    assert status == "UNKNOWN"


def test_naive_datetime_is_treated_as_utc():
    status = compute_freshness_status(
        connection_status="healthy",
        last_observation_time=(_NOW - timedelta(minutes=1)).replace(tzinfo=None),
        expected_update_frequency_seconds=_WEEKLY,
        now=_NOW,
    )
    assert status == "LIVE"
