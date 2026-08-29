"""Phase 1 free-data-feed integration (docs/data-sources.md): DataQualityService's
deterministic 0-100 scoring -- missing/impossible values, timestamp sanity, and a
jump check against the prior observation for the same series."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from data_service.quality import DataQualityService
from schemas import ObservationDraft

_NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)


def _draft(**overrides) -> ObservationDraft:
    defaults = dict(
        source="EIA",
        source_type="PUBLIC",
        series_id="EIA.NG.STORAGE.LOWER48",
        category="STORAGE",
        value=3200.0,
        unit="BCF",
        observation_time=_NOW - timedelta(days=1),
        publication_time=_NOW,
    )
    defaults.update(overrides)
    return ObservationDraft(**defaults)


def test_normal_observation_scores_100():
    service = DataQualityService()
    assert service.score(_draft(), now=_NOW) == 100.0


def test_missing_value_scores_zero():
    service = DataQualityService()
    draft = _draft()
    draft.value = None  # type: ignore[assignment] -- simulates a provider's malformed payload
    assert service.score(draft, now=_NOW) == 0.0


def test_negative_storage_value_is_penalized():
    service = DataQualityService()
    draft = _draft(value=-100.0)
    assert service.score(draft, now=_NOW) < 100.0


def test_impossible_temperature_is_penalized():
    service = DataQualityService()
    draft = _draft(category="WEATHER", unit="DEGF", value=999.0)
    assert service.score(draft, now=_NOW) < 100.0


def test_plausible_temperature_is_not_penalized():
    service = DataQualityService()
    draft = _draft(category="WEATHER", unit="DEGF", value=72.0)
    assert service.score(draft, now=_NOW) == 100.0


def test_future_dated_observation_is_penalized():
    service = DataQualityService()
    draft = _draft(observation_time=_NOW + timedelta(days=1))
    assert service.score(draft, now=_NOW) < 100.0


def test_large_jump_against_prior_is_penalized():
    service = DataQualityService()
    prior = _draft(value=3200.0)
    current = _draft(value=100_000.0)
    assert service.score(current, prior=prior, now=_NOW) < 100.0


def test_small_change_against_prior_is_not_penalized():
    service = DataQualityService()
    prior = _draft(value=3200.0)
    current = _draft(value=3250.0)
    assert service.score(current, prior=prior, now=_NOW) == 100.0


def test_score_never_goes_below_zero_even_with_multiple_penalties():
    service = DataQualityService()
    draft = _draft(value=-999.0, observation_time=_NOW + timedelta(days=5))
    assert service.score(draft, now=_NOW) == 0.0


def test_score_batch_uses_each_series_own_immediately_preceding_draft():
    service = DataQualityService()
    storage_a = _draft(series_id="A", value=100.0, observation_time=_NOW - timedelta(days=14))
    storage_b = _draft(series_id="A", value=100_000.0, observation_time=_NOW - timedelta(days=7))
    unrelated = _draft(series_id="B", value=50.0, observation_time=_NOW - timedelta(days=7))
    scores = service.score_batch([storage_a, storage_b, unrelated], now=_NOW)
    assert scores[0] == 100.0  # no prior in its own series -- nothing to jump-check against
    assert scores[1] < 100.0  # jumped against storage_a, the immediately-preceding draft in series A
    assert scores[2] == 100.0  # series B has no prior at all
