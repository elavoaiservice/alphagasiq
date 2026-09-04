from __future__ import annotations

from schemas import RiskLimits


def default_risk_limits() -> RiskLimits:
    """Conservative defaults for a paper-trading MVP; overridable by RISK_MANAGER/ADMIN
    via PUT /risk/limits."""
    return RiskLimits(
        max_position_size=500_000,
        max_risk_per_trade=25_000,
        max_daily_loss=75_000,
        max_drawdown=0.15,
        max_portfolio_var=100_000,
        max_sector_exposure=0.5,
        max_contract_exposure=0.35,
        max_correlated_exposure=0.6,
    )
