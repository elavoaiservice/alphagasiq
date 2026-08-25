"""Point-in-time correctness tests.

docs/architecture.md calls this "critical": a model must never be able to see an
observation before its `publication_time`. These tests are the platform's guarantee
against the classic EIA-style bug — a Friday `observation_time` whose Thursday
`publication_time` is nearly a week later — and they are written to fail loudly if
that guarantee is ever silently broken.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from quant_service.pit import as_of_filter, assert_no_leakage, latest_known_value
from schemas import DataClassification, TimeSeriesObservation


def make_obs(observation_time: datetime, publication_time: datetime, value: float = 1.0) -> TimeSeriesObservation:
    return TimeSeriesObservation(
        source="TEST",
        source_type=DataClassification.SIMULATED,
        series_id="TEST.SERIES",
        category="PRICE",
        value=value,
        unit="USD_MMBTU",
        observation_time=observation_time,
        publication_time=publication_time,
    )


DAY0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


class TestAsOfFilter:
    def test_excludes_observation_published_after_as_of(self):
        obs = make_obs(DAY0, DAY0 + timedelta(days=1))
        assert as_of_filter([obs], as_of=DAY0) == []

    def test_includes_observation_published_exactly_at_as_of(self):
        obs = make_obs(DAY0, DAY0)
        assert as_of_filter([obs], as_of=DAY0) == [obs]

    def test_includes_observation_published_before_as_of(self):
        obs = make_obs(DAY0, DAY0 - timedelta(hours=1))
        assert as_of_filter([obs], as_of=DAY0) == [obs]

    def test_the_eia_style_reporting_lag_scenario(self):
        """observation_time = the storage week's Friday; publication_time = the
        following Thursday. As of the Monday after the Friday, the observation must
        NOT be visible even though its observation_time has already passed —
        this is exactly the bug PIT filtering exists to prevent."""
        friday = DAY0
        following_thursday = friday + timedelta(days=6)
        obs = make_obs(friday, following_thursday)

        as_of_the_following_monday = friday + timedelta(days=3)
        assert as_of_filter([obs], as_of=as_of_the_following_monday) == []

        as_of_report_day = following_thursday
        assert as_of_filter([obs], as_of=as_of_report_day) == [obs]

    def test_naive_filter_by_observation_time_would_leak_but_pit_does_not(self):
        """Regression guard for the exact anti-pattern this module exists to forbid:
        filtering by observation_time alone would have wrongly included this
        observation days before it was actually knowable."""
        friday = DAY0
        following_thursday = friday + timedelta(days=6)
        obs = make_obs(friday, following_thursday)
        as_of = friday + timedelta(days=1)

        naively_filtered_by_observation_time = [o for o in [obs] if o.observation_time <= as_of]
        assert naively_filtered_by_observation_time == [obs]  # the bug, if it existed

        assert as_of_filter([obs], as_of=as_of) == []  # PIT correctly excludes it

    def test_preserves_order(self):
        obs1 = make_obs(DAY0, DAY0, value=1.0)
        obs2 = make_obs(DAY0 + timedelta(days=1), DAY0 + timedelta(days=1), value=2.0)
        result = as_of_filter([obs1, obs2], as_of=DAY0 + timedelta(days=2))
        assert [o.value for o in result] == [1.0, 2.0]

    def test_naive_utc_and_aware_as_of_both_work(self):
        obs = make_obs(DAY0, DAY0)
        naive_as_of = datetime(2026, 1, 1)
        assert as_of_filter([obs], as_of=naive_as_of) == [obs]

    def test_empty_input(self):
        assert as_of_filter([], as_of=DAY0) == []


class TestLatestKnownValue:
    def test_returns_most_recently_observed_among_knowable(self):
        old = make_obs(DAY0, DAY0, value=1.0)
        new_but_unpublished = make_obs(DAY0 + timedelta(days=5), DAY0 + timedelta(days=10), value=2.0)
        result = latest_known_value([old, new_but_unpublished], as_of=DAY0 + timedelta(days=6))
        assert result is old  # the "new" one isn't knowable yet

    def test_once_published_becomes_the_latest_known(self):
        old = make_obs(DAY0, DAY0, value=1.0)
        new = make_obs(DAY0 + timedelta(days=5), DAY0 + timedelta(days=5), value=2.0)
        result = latest_known_value([old, new], as_of=DAY0 + timedelta(days=6))
        assert result is new

    def test_returns_none_when_nothing_knowable(self):
        obs = make_obs(DAY0, DAY0 + timedelta(days=5))
        assert latest_known_value([obs], as_of=DAY0) is None


class TestAssertNoLeakage:
    def test_raises_on_future_publication(self):
        obs = make_obs(DAY0, DAY0 + timedelta(days=1))
        with pytest.raises(ValueError, match="look-ahead bias"):
            assert_no_leakage([obs], as_of=DAY0)

    def test_passes_when_everything_is_knowable(self):
        obs = make_obs(DAY0, DAY0)
        assert_no_leakage([obs], as_of=DAY0)  # must not raise

    def test_reports_count_of_leaked_observations(self):
        leaked = [make_obs(DAY0, DAY0 + timedelta(days=i)) for i in (1, 2, 3)]
        with pytest.raises(ValueError, match="3 observation"):
            assert_no_leakage(leaked, as_of=DAY0)
