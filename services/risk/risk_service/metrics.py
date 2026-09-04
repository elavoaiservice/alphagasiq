"""Portfolio risk metrics: gross/net exposure, greeks, P&L, VaR/ES, drawdown,
correlation, concentration, liquidity.

Pure, dependency-light functions operating on a list of `PositionSnapshot` so they are
testable without a database.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class PositionSnapshot:
    instrument: str
    sector: str
    quantity: float
    price: float
    avg_price: float
    delta: float = 1.0
    gamma: float = 0.0
    vega: float = 0.0
    daily_return_series: tuple[float, ...] = ()  # historical daily P&L returns, most recent last

    @property
    def market_value(self) -> float:
        return self.quantity * self.price

    @property
    def unrealized_pnl(self) -> float:
        return (self.price - self.avg_price) * self.quantity


@dataclass(frozen=True)
class PortfolioRiskSummary:
    gross_exposure: float
    net_exposure: float
    delta: float
    gamma: float
    vega: float
    unrealized_pnl: float
    var_95: float
    expected_shortfall_95: float
    max_drawdown: float
    concentration_hhi: float
    largest_position_share: float


def gross_exposure(positions: list[PositionSnapshot]) -> float:
    return sum(abs(p.market_value) for p in positions)


def net_exposure(positions: list[PositionSnapshot]) -> float:
    return sum(p.market_value for p in positions)


def portfolio_greeks(positions: list[PositionSnapshot]) -> tuple[float, float, float]:
    delta = sum(p.delta * p.quantity for p in positions)
    gamma = sum(p.gamma * p.quantity for p in positions)
    vega = sum(p.vega * p.quantity for p in positions)
    return delta, gamma, vega


def unrealized_pnl(positions: list[PositionSnapshot]) -> float:
    return sum(p.unrealized_pnl for p in positions)


def historical_var(returns: list[float], confidence: float = 0.95) -> float:
    """Historical-simulation VaR: the loss at the given confidence level, expressed as
    a positive number. Empty/short series returns 0.0 (nothing to measure yet)."""
    if not returns:
        return 0.0
    sorted_returns = sorted(returns)
    idx = max(0, int((1 - confidence) * len(sorted_returns)) - 1)
    worst = sorted_returns[idx]
    return max(0.0, -worst)


def expected_shortfall(returns: list[float], confidence: float = 0.95) -> float:
    """Average loss beyond the VaR threshold (a.k.a. CVaR)."""
    if not returns:
        return 0.0
    sorted_returns = sorted(returns)
    cutoff = max(1, int((1 - confidence) * len(sorted_returns)))
    tail = sorted_returns[:cutoff]
    return max(0.0, -statistics.fmean(tail))


def max_drawdown(equity_curve: list[float]) -> float:
    if not equity_curve:
        return 0.0
    peak = equity_curve[0]
    worst = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        drawdown = (peak - value) / peak if peak else 0.0
        worst = max(worst, drawdown)
    return round(worst, 4)


def concentration_hhi(positions: list[PositionSnapshot]) -> float:
    """Herfindahl-Hirschman Index over absolute exposure share by instrument, 0-1
    (1.0 = fully concentrated in a single instrument)."""
    total = gross_exposure(positions)
    if total == 0:
        return 0.0
    shares = [abs(p.market_value) / total for p in positions]
    return round(sum(s**2 for s in shares), 4)


def largest_position_share(positions: list[PositionSnapshot]) -> float:
    total = gross_exposure(positions)
    if total == 0 or not positions:
        return 0.0
    return round(max(abs(p.market_value) for p in positions) / total, 4)


def sector_exposure(positions: list[PositionSnapshot]) -> dict[str, float]:
    out: dict[str, float] = {}
    for p in positions:
        out[p.sector] = out.get(p.sector, 0.0) + abs(p.market_value)
    return out


def correlation_matrix(positions: list[PositionSnapshot]) -> dict[str, dict[str, float]]:
    matrix: dict[str, dict[str, float]] = {}
    for a in positions:
        matrix[a.instrument] = {}
        for b in positions:
            if len(a.daily_return_series) < 2 or len(b.daily_return_series) < 2:
                corr = 1.0 if a.instrument == b.instrument else 0.0
            else:
                n = min(len(a.daily_return_series), len(b.daily_return_series))
                try:
                    corr = statistics.correlation(
                        a.daily_return_series[-n:], b.daily_return_series[-n:]
                    )
                except statistics.StatisticsError:
                    corr = 0.0
            matrix[a.instrument][b.instrument] = round(corr, 3)
    return matrix


def summarize(positions: list[PositionSnapshot], equity_curve: list[float]) -> PortfolioRiskSummary:
    delta, gamma, vega = portfolio_greeks(positions)
    portfolio_returns = _portfolio_daily_returns(positions)
    return PortfolioRiskSummary(
        gross_exposure=round(gross_exposure(positions), 2),
        net_exposure=round(net_exposure(positions), 2),
        delta=round(delta, 2),
        gamma=round(gamma, 4),
        vega=round(vega, 2),
        unrealized_pnl=round(unrealized_pnl(positions), 2),
        var_95=round(historical_var(portfolio_returns), 2),
        expected_shortfall_95=round(expected_shortfall(portfolio_returns), 2),
        max_drawdown=max_drawdown(equity_curve),
        concentration_hhi=concentration_hhi(positions),
        largest_position_share=largest_position_share(positions),
    )


def _portfolio_daily_returns(positions: list[PositionSnapshot]) -> list[float]:
    if not positions:
        return []
    n = min((len(p.daily_return_series) for p in positions), default=0)
    if n == 0:
        return []
    return [sum(p.daily_return_series[-n:][i] * p.quantity for p in positions) for i in range(n)]
