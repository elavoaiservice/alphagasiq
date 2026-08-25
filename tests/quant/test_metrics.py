import math

import pytest
from quant_service.metrics import (
    brier_score,
    directional_accuracy,
    hit_rate,
    mae,
    max_drawdown,
    profit_factor,
    rmse,
    sharpe_ratio,
    sortino_ratio,
)


class TestMae:
    def test_known_values(self):
        assert mae([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 0.0
        assert mae([1.0, 2.0], [2.0, 4.0]) == pytest.approx(1.5)

    def test_empty(self):
        assert mae([], []) == 0.0

    def test_mismatched_lengths_raises(self):
        with pytest.raises(ValueError):
            mae([1.0], [1.0, 2.0])


class TestRmse:
    def test_known_values(self):
        assert rmse([0.0, 0.0], [3.0, 4.0]) == pytest.approx(math.sqrt((9 + 16) / 2))

    def test_penalizes_large_errors_more_than_mae(self):
        actual = [0.0, 0.0, 0.0, 0.0]
        predicted_uniform = [1.0, 1.0, 1.0, 1.0]
        predicted_spiky = [0.0, 0.0, 0.0, 4.0]
        assert mae(actual, predicted_uniform) == mae(actual, predicted_spiky)
        assert rmse(actual, predicted_spiky) > rmse(actual, predicted_uniform)


class TestDirectionalAccuracy:
    def test_all_correct(self):
        assert directional_accuracy([1.0, -1.0, 2.0], [0.5, -0.5, 1.0]) == 1.0

    def test_all_wrong(self):
        assert directional_accuracy([1.0, -1.0], [-0.5, 0.5]) == 0.0

    def test_both_zero_counts_as_correct(self):
        assert directional_accuracy([0.0], [0.0]) == 1.0

    def test_one_zero_one_nonzero_is_a_miss(self):
        assert directional_accuracy([0.0], [1.0]) == 0.0

    def test_empty_returns_zero(self):
        assert directional_accuracy([], []) == 0.0


class TestHitRate:
    def test_basic(self):
        assert hit_rate([True, True, False, False]) == 0.5

    def test_empty(self):
        assert hit_rate([]) == 0.0

    def test_all_hits(self):
        assert hit_rate([True, True]) == 1.0


class TestProfitFactor:
    def test_basic_ratio(self):
        assert profit_factor([10.0, -5.0, 20.0, -5.0]) == pytest.approx(30.0 / 10.0)

    def test_no_losses_is_infinite(self):
        assert profit_factor([10.0, 5.0]) == math.inf

    def test_no_trades_is_none(self):
        assert profit_factor([]) is None

    def test_all_zero_is_none(self):
        assert profit_factor([0.0, 0.0]) is None


class TestSharpeAndSortino:
    def test_sharpe_none_for_short_series(self):
        assert sharpe_ratio([0.01]) is None

    def test_sharpe_none_for_zero_variance(self):
        assert sharpe_ratio([0.01, 0.01, 0.01]) is None

    def test_sharpe_positive_for_positive_mean_returns(self):
        result = sharpe_ratio([0.02, 0.01, 0.03, 0.015, 0.025])
        assert result is not None
        assert result > 0

    def test_sortino_ignores_upside_volatility(self):
        low_upside_vol = [0.01, 0.01, 0.01, -0.01, 0.01]
        high_upside_vol = [0.01, 0.05, 0.01, -0.01, 0.01]
        sortino_low = sortino_ratio(low_upside_vol)
        sortino_high = sortino_ratio(high_upside_vol)
        # Higher upside volatility with the same downside should not be penalized by Sortino.
        assert sortino_high >= sortino_low


class TestMaxDrawdown:
    def test_monotonic_increase_has_zero_drawdown(self):
        assert max_drawdown([100, 110, 120, 130]) == 0.0

    def test_known_drawdown(self):
        assert max_drawdown([100, 120, 90, 130]) == pytest.approx((120 - 90) / 120)

    def test_empty_curve(self):
        assert max_drawdown([]) == 0.0


class TestBrierScore:
    def test_perfect_forecast_scores_zero(self):
        assert brier_score([1.0, 0.0], [True, False]) == 0.0

    def test_maximally_wrong_forecast_scores_one(self):
        assert brier_score([0.0, 1.0], [True, False]) == 1.0

    def test_coin_flip_scores_quarter(self):
        assert brier_score([0.5, 0.5, 0.5, 0.5], [True, False, True, False]) == pytest.approx(0.25)

    def test_empty(self):
        assert brier_score([], []) == 0.0
