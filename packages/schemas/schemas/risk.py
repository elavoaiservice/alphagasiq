from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .enums import RiskVerdict


class RiskLimits(BaseModel):
    max_position_size: float
    max_risk_per_trade: float
    max_daily_loss: float
    max_drawdown: float
    max_portfolio_var: float
    max_sector_exposure: float
    max_contract_exposure: float
    max_correlated_exposure: float
    effective_from: datetime = Field(default_factory=datetime.utcnow)
    effective_to: datetime | None = None
    set_by_user_id: str | None = None


class RiskRuleOutcome(BaseModel):
    rule: str
    verdict: RiskVerdict
    passed: bool
    detail: str


class RiskCheckResult(BaseModel):
    check_id: UUID = Field(default_factory=uuid4)
    trade_id: UUID
    verdict: RiskVerdict
    rule_results: list[RiskRuleOutcome]
    governor_version: str
    evaluated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def blocking_rule(self) -> RiskRuleOutcome | None:
        for r in self.rule_results:
            if not r.passed:
                return r
        return None
