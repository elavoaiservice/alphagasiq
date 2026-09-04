"""Walk-forward evaluation metrics (docs/architecture.md QUANTITATIVE PLATFORM).

Every function is a pure, dependency-light computation over parallel lists so they're
trivially unit-testable and usable from both `backtesting.py` and any agent that wants
to report a metric on its own.
"""

from __future__ import annotations

import math
import statistics


def mae(actual: list[float], predicted: list[float]) -> float:
    _check_lengths(actual, predicted)
    if not actual:
        return 0.0
    return sum(abs(a - p) for a, p in zip(actual, predicted)) / len(actual)


def rmse(actual: list[float], predicted: list[float]) -> float:
    _check_lengths(actual, predicted)
    if not actual:
        return 0.0
    return math.sqrt(sum((a - p) ** 2 for a, p in zip(actual, predicted)) / len(actual))


def directional_accuracy(actual_changes: list[float], predicted_changes: list[float]) -> float:
    """Fraction of folds where the predicted change and the actual change had the
    same sign. Flat (zero) actual/predicted changes count as a miss unless both are
    exactly zero, since "no move" is a specific, checkable prediction."""
    _check_lengths(actual_changes, predicted_changes)
    if not actual_changes:
        return 0.0
    correct = sum(1 for a, p in zip(actual_changes, predicted_changes) if _same_sign(a, p))
    return correct / len(actual_changes)


def hit_rate(hits: list[bool]) -> float:
    """Generic win-rate style metric: fraction of True entries."""
    if not hits:
        return 0.0
    return sum(1 for h in hits if h) / len(hits)


def profit_factor(pnls: list[float]) -> float | None:
    gains = sum(p for p in pnls if p > 0)
    losses = sum(-p for p in pnls if p < 0)
    if losses == 0:
        return None if gains == 0 else math.inf
    return gains / losses


def sharpe_ratio(returns: list[float], *, risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float | None:
    if len(returns) < 2:
        return None
    excess = [r - risk_free_rate / periods_per_year for r in returns]
    mean = statistics.fmean(excess)
    std = statistics.pstdev(excess)
    if std == 0:
        return None
    return (mean / std) * math.sqrt(periods_per_year)


def sortino_ratio(returns: list[float], *, risk_free_rate: float = 0.0, periods_per_year: int = 252) -> float | None:
    if len(returns) < 2:
        return None
    excess = [r - risk_free_rate / periods_per_year for r in returns]
    mean = statistics.fmean(excess)
    downside = [min(0.0, r) for r in excess]
    downside_std = math.sqrt(sum(d**2 for d in downside) / len(downside))
    if downside_std == 0:
        return None
    return (mean / downside_std) * math.sqrt(periods_per_year)


def max_drawdown(equity_curve: list[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    worst = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        drawdown = (peak - value) / peak if peak else 0.0
        worst = max(worst, drawdown)
    return round(worst, 6)


def brier_score(probabilities: list[float], outcomes: list[bool]) -> float:
    """Mean squared error of a probabilistic forecast against the realized binary
    outcome — the standard calibration metric for "up_probability" style forecasts.
    0 is perfect, 0.25 is what a coin-flip forecaster scores, 1 is maximally wrong."""
    _check_lengths(probabilities, outcomes)
    if not probabilities:
        return 0.0
    return sum((p - (1.0 if o else 0.0)) ** 2 for p, o in zip(probabilities, outcomes)) / len(probabilities)


def _same_sign(a: float, b: float) -> bool:
    if a == 0 and b == 0:
        return True
    return (a > 0 and b > 0) or (a < 0 and b < 0)


def _check_lengths(a: list, b: list) -> None:
    if len(a) != len(b):
        raise ValueError(f"Parallel lists must be the same length, got {len(a)} and {len(b)}")
