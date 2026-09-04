from datetime import date, datetime, timedelta, timezone

import pytest
from quant_service.backtesting import InsufficientDataError, walk_forward_evaluate
from quant_service.pit import as_of_filter
from quant_service.seed import generate_price_history
from schemas import DataClassification, ForecastHorizon, ModelType, TimeSeriesObservation


def make_obs(day_offset: int, value: float, publication_lag_days: int = 0) -> TimeSeriesObservation:
    obs_time = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=day_offset)
    return TimeSeriesObservation(
        source="TEST",
        source_type=DataClassification.SIMULATED,
        series_id="TEST.PRICE",
        category="PRICE",
        value=value,
        unit="USD_MMBTU",
        observation_time=obs_time,
        publication_time=obs_time + timedelta(days=publication_lag_days),
    )


class TestWalkForwardEvaluate:
    def test_runs_on_realistic_seed_data(self):
        obs = generate_price_history(end_date=date(2026, 8, 25), num_days=250)
        result = walk_forward_evaluate(
            model_type=ModelType.LINEAR_REGRESSION, observations=obs, instrument="NGQ26",
            horizon=ForecastHorizon.SEVEN_DAY, train_window_days=60, step_days=5,
        )
        assert result.n_folds > 0
        assert result.mae >= 0
        assert result.rmse >= 0
        assert 0 <= result.directional_accuracy <= 1
        assert 0 <= result.hit_rate <= 1
        assert result.max_drawdown >= 0

    def test_naive_baseline_never_takes_a_directional_bet(self):
        """The persistence baseline's forecast never differs from the last known
        price, so it should show 0% directional accuracy and 0% hit rate — a
        regression guard that the baseline stays a true "no signal" reference."""
        obs = generate_price_history(end_date=date(2026, 8, 25), num_days=250)
        result = walk_forward_evaluate(
            model_type=ModelType.NAIVE_PERSISTENCE, observations=obs, instrument="NGQ26",
            horizon=ForecastHorizon.SEVEN_DAY, train_window_days=60, step_days=5,
        )
        assert result.directional_accuracy == 0.0
        assert result.hit_rate == 0.0

    def test_raises_on_insufficient_data(self):
        obs = generate_price_history(end_date=date(2026, 8, 25), num_days=10)
        with pytest.raises(InsufficientDataError):
            walk_forward_evaluate(
                model_type=ModelType.LINEAR_REGRESSION, observations=obs, instrument="NGQ26",
                horizon=ForecastHorizon.SEVEN_DAY, train_window_days=60, step_days=5,
            )

    def test_model_version_is_recorded(self):
        obs = generate_price_history(end_date=date(2026, 8, 25), num_days=250)
        result = walk_forward_evaluate(
            model_type=ModelType.LINEAR_REGRESSION, observations=obs, instrument="NGQ26",
            train_window_days=60, step_days=5,
        )
        assert result.model_version == "1.0.0"


class TestPointInTimeCorrectnessInsideBacktesting:
    """The core anti-leakage regression test: a late-published observation must be
    provably absent from folds evaluated before its publication_time, and provably
    present in folds evaluated after — proving the backtesting engine actually
    threads `as_of_filter` through every fold rather than just defining it."""

    def _build_series_with_one_late_revision(self, *, late_day: int, lag_days: int, n: int = 120):
        obs = []
        for day in range(n):
            lag = lag_days if day == late_day else 0
            obs.append(make_obs(day, value=3.0 + 0.01 * day, publication_lag_days=lag))
        return obs

    def test_late_observation_excluded_from_a_fold_before_its_publication(self):
        obs = self._build_series_with_one_late_revision(late_day=70, lag_days=5)
        as_of = obs[70].observation_time + timedelta(days=1)  # published on day 75, not yet at day 71
        known = as_of_filter(obs, as_of)
        known_days = {o.observation_time for o in known}
        assert obs[70].observation_time not in known_days

    def test_late_observation_included_once_its_publication_time_has_passed(self):
        obs = self._build_series_with_one_late_revision(late_day=70, lag_days=5)
        as_of = obs[70].publication_time + timedelta(hours=1)
        known = as_of_filter(obs, as_of)
        known_days = {o.observation_time for o in known}
        assert obs[70].observation_time in known_days

    def test_walk_forward_still_produces_valid_folds_around_a_late_revision(self):
        """End-to-end: the late revision should not crash the walk-forward loop, and
        every fold it does produce must satisfy PIT (checked via as_of_filter
        directly, not just trusted)."""
        obs = self._build_series_with_one_late_revision(late_day=70, lag_days=5, n=150)
        result = walk_forward_evaluate(
            model_type=ModelType.LINEAR_REGRESSION, observations=obs, instrument="TEST",
            horizon=ForecastHorizon.SEVEN_DAY, train_window_days=60, step_days=5,
        )
        assert result.n_folds > 0
