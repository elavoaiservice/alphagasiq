"""Walk-forward backtesting engine (docs/architecture.md QUANTITATIVE PLATFORM).

Every fold trains and forecasts using ONLY what `pit.as_of_filter` says was knowable
at that fold's `as_of` moment — this is what makes the resulting metrics trustworthy
rather than optimistic. See `tests/quant/test_backtesting.py` for a regression test
that a late-published observation is provably excluded from the fold that precedes its
publication and provably included in the fold that follows it.
"""

from __future__ import annotations

from datetime import timedelta

from schemas import BacktestResult, ForecastHorizon, ModelType, TimeSeriesObservation

from .forecast import HORIZON_STEPS_DAYS
from .metrics import (
    directional_accuracy,
    hit_rate,
    mae,
    max_drawdown,
    profit_factor,
    rmse,
    sharpe_ratio,
    sortino_ratio,
)
from .models.registry import build_model
from .pit import as_of_filter


class InsufficientDataError(ValueError):
    pass


def walk_forward_evaluate(
    *,
    model_type: ModelType,
    observations: list[TimeSeriesObservation],
    instrument: str,
    horizon: ForecastHorizon = ForecastHorizon.ONE_DAY,
    train_window_days: int = 60,
    step_days: int = 5,
) -> BacktestResult:
    horizon_days = max(1, round(HORIZON_STEPS_DAYS[horizon]))
    obs_sorted = sorted(observations, key=lambda o: o.observation_time)
    n = len(obs_sorted)
    if n < train_window_days + horizon_days + step_days:
        raise InsufficientDataError(
            f"Need at least {train_window_days + horizon_days + step_days} observations, got {n}"
        )

    predicted_prices: list[float] = []
    actual_prices: list[float] = []
    predicted_changes: list[float] = []
    actual_changes: list[float] = []
    strategy_returns: list[float] = []

    for fold_start in range(train_window_days, n - horizon_days, step_days):
        as_of = obs_sorted[fold_start].observation_time + timedelta(days=1)
        known = as_of_filter(obs_sorted, as_of)
        training_window = known[-train_window_days:]
        if len(training_window) < 2:
            continue

        anchor = training_window[-1]
        anchor_idx = obs_sorted.index(anchor)
        future_idx = anchor_idx + horizon_days
        if future_idx >= n:
            continue

        last_known_price = anchor.value
        actual_price = obs_sorted[future_idx].value

        x = list(range(len(training_window)))
        y = [o.value for o in training_window]
        model = build_model(model_type)
        model.fit(x, y)
        predicted_price = model.predict(horizon_days)

        predicted_change = predicted_price - last_known_price
        actual_change = actual_price - last_known_price
        strategy_return = 0.0
        if predicted_change != 0 and last_known_price > 0:
            direction = 1 if predicted_change > 0 else -1
            strategy_return = direction * (actual_price / last_known_price - 1)

        predicted_prices.append(predicted_price)
        actual_prices.append(actual_price)
        predicted_changes.append(predicted_change)
        actual_changes.append(actual_change)
        strategy_returns.append(strategy_return)

    if not predicted_prices:
        raise InsufficientDataError("No valid walk-forward folds were produced from the given observations/window")

    equity_curve = [1.0]
    for r in strategy_returns:
        equity_curve.append(equity_curve[-1] * (1 + r))

    model_version = build_model(model_type).version

    return BacktestResult(
        model_type=model_type,
        model_version=model_version,
        instrument=instrument,
        horizon=horizon,
        n_folds=len(predicted_prices),
        mae=round(mae(actual_prices, predicted_prices), 4),
        rmse=round(rmse(actual_prices, predicted_prices), 4),
        directional_accuracy=round(directional_accuracy(actual_changes, predicted_changes), 4),
        hit_rate=round(hit_rate([r > 0 for r in strategy_returns]), 4),
        sharpe_ratio=_round_or_none(sharpe_ratio(strategy_returns, periods_per_year=252 // step_days or 1)),
        sortino_ratio=_round_or_none(sortino_ratio(strategy_returns, periods_per_year=252 // step_days or 1)),
        max_drawdown=round(max_drawdown(equity_curve), 4),
        profit_factor=_round_or_none(profit_factor(strategy_returns)),
    )


def _round_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    if value != value or value in (float("inf"), float("-inf")):  # NaN/inf guard
        return None
    return round(value, 4)
