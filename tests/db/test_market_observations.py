"""Bitemporal correctness tests for `SqlAppRepository.save_market_observation()` /
`list_market_observations_as_of()` (docs/alpha-intelligence.md section 9,
AlphaReplay(TM)). These are the tests the Milestone 6 plan called out explicitly:
proving revision-supersession never loses history, and proving an "as known at
<as_of>" query is unaffected by a correction that arrived after that moment even
though the correction has since been recorded.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from db import SqlAppRepository
from schemas import DataClassification, TimeSeriesObservation


def make_observation(
    *,
    series_id: str = "NG.FUT.M1",
    value: float,
    observation_time: datetime,
    publication_time: datetime,
    revision_number: int = 0,
) -> TimeSeriesObservation:
    return TimeSeriesObservation(
        source="test",
        source_type=DataClassification.SIMULATED,
        series_id=series_id,
        category="PRICE",
        value=value,
        unit="USD/MMBtu",
        observation_time=observation_time,
        publication_time=publication_time,
        revision_number=revision_number,
    )


@pytest.fixture
async def repo():
    r = SqlAppRepository("sqlite+aiosqlite:///:memory:")
    await r.init_schema()
    yield r
    await r.dispose()


async def test_first_observation_for_a_series_is_the_current_revision(repo):
    obs_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    pub_time = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    await repo.save_market_observation(
        make_observation(value=3.0, observation_time=obs_time, publication_time=pub_time)
    )

    current = await repo.list_market_observations_as_of(series_id="NG.FUT.M1")
    assert len(current) == 1
    assert current[0]["value"] == 3.0
    assert current[0]["valid_to"] is None


async def test_a_later_revision_supersedes_without_deleting_the_prior_row(repo):
    obs_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first_pub = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    second_pub = datetime(2026, 1, 2, tzinfo=timezone.utc)

    await repo.save_market_observation(
        make_observation(value=3.0, observation_time=obs_time, publication_time=first_pub, revision_number=0)
    )
    await repo.save_market_observation(
        make_observation(value=3.2, observation_time=obs_time, publication_time=second_pub, revision_number=1)
    )

    # The as-of-now view sees only the latest revision -- the prior one is closed
    # out (`valid_to` set), not deleted.
    current = await repo.list_market_observations_as_of(series_id="NG.FUT.M1")
    assert len(current) == 1
    assert current[0]["value"] == 3.2
    assert current[0]["valid_to"] is None


async def test_a_duplicate_or_stale_revision_is_a_no_op(repo):
    obs_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first_pub = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    second_pub = datetime(2026, 1, 2, tzinfo=timezone.utc)

    await repo.save_market_observation(
        make_observation(value=3.0, observation_time=obs_time, publication_time=first_pub, revision_number=1)
    )
    # A revision_number no higher than the current one must not overwrite it.
    await repo.save_market_observation(
        make_observation(value=99.0, observation_time=obs_time, publication_time=second_pub, revision_number=1)
    )

    current = await repo.list_market_observations_as_of(series_id="NG.FUT.M1")
    assert len(current) == 1
    assert current[0]["value"] == 3.0


async def test_as_of_before_the_correction_still_recovers_the_original_belief(repo):
    """The core invariant: querying "as known at moment X" must never be affected
    by a correction that arrived after X, even though that correction has since
    been recorded as the new current revision."""
    obs_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first_pub = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    second_pub = datetime(2026, 1, 5, tzinfo=timezone.utc)
    between = datetime(2026, 1, 3, tzinfo=timezone.utc)

    await repo.save_market_observation(
        make_observation(value=3.0, observation_time=obs_time, publication_time=first_pub, revision_number=0)
    )
    await repo.save_market_observation(
        make_observation(value=3.5, observation_time=obs_time, publication_time=second_pub, revision_number=1)
    )

    as_of_between = await repo.list_market_observations_as_of(series_id="NG.FUT.M1", as_of=between)
    assert len(as_of_between) == 1
    assert as_of_between[0]["value"] == 3.0  # the correction hadn't happened yet

    as_of_after = await repo.list_market_observations_as_of(series_id="NG.FUT.M1", as_of=second_pub + timedelta(hours=1))
    assert len(as_of_after) == 1
    assert as_of_after[0]["value"] == 3.5  # now the correction is visible

    as_of_before_first_publication = await repo.list_market_observations_as_of(
        series_id="NG.FUT.M1", as_of=first_pub - timedelta(hours=1)
    )
    assert as_of_before_first_publication == []  # honest emptiness, not a fabricated value


async def test_series_id_filter_does_not_leak_other_series(repo):
    obs_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    pub_time = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    await repo.save_market_observation(
        make_observation(series_id="NG.FUT.M1", value=3.0, observation_time=obs_time, publication_time=pub_time)
    )
    await repo.save_market_observation(
        make_observation(series_id="NG.FUT.M2", value=3.5, observation_time=obs_time, publication_time=pub_time)
    )

    m1_only = await repo.list_market_observations_as_of(series_id="NG.FUT.M1")
    assert [o["series_id"] for o in m1_only] == ["NG.FUT.M1"]

    everything = await repo.list_market_observations_as_of()
    assert {o["series_id"] for o in everything} == {"NG.FUT.M1", "NG.FUT.M2"}
