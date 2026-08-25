"""The Risk Governor: a deterministic, non-LLM rules engine with absolute veto
authority over every proposed trade.

No agent, committee, or LLM call can override a failed hard risk rule here. This
module has zero dependency on any LLM provider and zero network calls of its own —
every input it needs is passed in already-resolved, so its output is a pure function
of its input and therefore trivially and exhaustively testable (see
tests/risk/test_governor.py, which carries the highest coverage bar in the repo).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from schemas import RiskCheckResult, RiskLimits, RiskRuleOutcome, RiskVerdict, TradeIdea

GOVERNOR_VERSION = "1.0.0"
_NIL_TRADE_ID = UUID("00000000-0000-0000-0000-000000000000")


@dataclass
class RiskContext:
    """Every fact the Risk Governor needs, already resolved by the caller (the
    Risk Engine / approval workflow) before `RiskGovernor.evaluate()` is invoked."""

    trade: TradeIdea
    limits: RiskLimits

    required_data_is_fresh: bool = True
    stale_sources: list[str] = field(default_factory=list)

    critical_provider_available: bool = True
    unavailable_providers: list[str] = field(default_factory=list)

    proposed_position_size: float = 0.0
    current_daily_loss: float = 0.0
    current_drawdown: float = 0.0

    strategy_approved: bool = True
    model_version: str = "unapproved"
    approved_model_versions: frozenset[str] = field(default_factory=frozenset)

    trade_confidence: float = 1.0
    min_confidence_threshold: float = 0.55

    volatility_zscore: float = 0.0
    abnormal_volatility_zscore_threshold: float = 3.0

    trading_halted: bool = False

    # Configurable: when a critical provider is unavailable, BLOCK outright or
    # require a human to decide. Defaults to the stricter BLOCK.
    on_critical_provider_unavailable: RiskVerdict = RiskVerdict.BLOCK


def _rule_trading_halted(ctx: RiskContext) -> RiskRuleOutcome:
    if ctx.trading_halted:
        return RiskRuleOutcome(
            rule="trading_halted",
            verdict=RiskVerdict.HALT,
            passed=False,
            detail="Trading is currently halted platform-wide pending human clearance.",
        )
    return RiskRuleOutcome(rule="trading_halted", verdict=RiskVerdict.ALLOW, passed=True, detail="ok")


def _rule_data_freshness(ctx: RiskContext) -> RiskRuleOutcome:
    if not ctx.required_data_is_fresh:
        return RiskRuleOutcome(
            rule="data_freshness",
            verdict=RiskVerdict.BLOCK,
            passed=False,
            detail=f"Stale required data sources: {', '.join(ctx.stale_sources) or 'unspecified'}",
        )
    return RiskRuleOutcome(rule="data_freshness", verdict=RiskVerdict.ALLOW, passed=True, detail="ok")


def _rule_critical_provider(ctx: RiskContext) -> RiskRuleOutcome:
    if not ctx.critical_provider_available:
        return RiskRuleOutcome(
            rule="critical_provider_availability",
            verdict=ctx.on_critical_provider_unavailable,
            passed=False,
            detail=f"Unavailable critical providers: {', '.join(ctx.unavailable_providers) or 'unspecified'}",
        )
    return RiskRuleOutcome(
        rule="critical_provider_availability", verdict=RiskVerdict.ALLOW, passed=True, detail="ok"
    )


def _rule_position_size(ctx: RiskContext) -> RiskRuleOutcome:
    if ctx.proposed_position_size > ctx.limits.max_position_size:
        return RiskRuleOutcome(
            rule="max_position_size",
            verdict=RiskVerdict.BLOCK,
            passed=False,
            detail=(
                f"Proposed position {ctx.proposed_position_size} exceeds limit "
                f"{ctx.limits.max_position_size}"
            ),
        )
    risk_per_trade = abs(ctx.trade.entry - ctx.trade.stop_or_invalidation) * ctx.proposed_position_size
    if risk_per_trade > ctx.limits.max_risk_per_trade:
        return RiskRuleOutcome(
            rule="max_risk_per_trade",
            verdict=RiskVerdict.BLOCK,
            passed=False,
            detail=f"Risk per trade {risk_per_trade:.2f} exceeds limit {ctx.limits.max_risk_per_trade}",
        )
    return RiskRuleOutcome(rule="max_position_size", verdict=RiskVerdict.ALLOW, passed=True, detail="ok")


def _rule_daily_loss(ctx: RiskContext) -> RiskRuleOutcome:
    if ctx.current_daily_loss >= ctx.limits.max_daily_loss:
        return RiskRuleOutcome(
            rule="max_daily_loss",
            verdict=RiskVerdict.BLOCK_NEW_RISK,
            passed=False,
            detail=f"Daily loss {ctx.current_daily_loss} has reached limit {ctx.limits.max_daily_loss}",
        )
    return RiskRuleOutcome(rule="max_daily_loss", verdict=RiskVerdict.ALLOW, passed=True, detail="ok")


def _rule_drawdown(ctx: RiskContext) -> RiskRuleOutcome:
    if ctx.current_drawdown >= ctx.limits.max_drawdown:
        return RiskRuleOutcome(
            rule="max_drawdown",
            verdict=RiskVerdict.HALT,
            passed=False,
            detail=f"Drawdown {ctx.current_drawdown} has reached limit {ctx.limits.max_drawdown}",
        )
    return RiskRuleOutcome(rule="max_drawdown", verdict=RiskVerdict.ALLOW, passed=True, detail="ok")


def _rule_strategy_approved(ctx: RiskContext) -> RiskRuleOutcome:
    if not ctx.strategy_approved:
        return RiskRuleOutcome(
            rule="strategy_approved",
            verdict=RiskVerdict.BLOCK,
            passed=False,
            detail=f"Strategy '{ctx.trade.strategy}' is not on the approved-strategy list.",
        )
    return RiskRuleOutcome(rule="strategy_approved", verdict=RiskVerdict.ALLOW, passed=True, detail="ok")


def _rule_model_version_approved(ctx: RiskContext) -> RiskRuleOutcome:
    if ctx.approved_model_versions and ctx.model_version not in ctx.approved_model_versions:
        return RiskRuleOutcome(
            rule="model_version_approved",
            verdict=RiskVerdict.BLOCK,
            passed=False,
            detail=f"Model version '{ctx.model_version}' is not in the approved-model registry.",
        )
    return RiskRuleOutcome(
        rule="model_version_approved", verdict=RiskVerdict.ALLOW, passed=True, detail="ok"
    )


def _rule_confidence_threshold(ctx: RiskContext) -> RiskRuleOutcome:
    if ctx.trade_confidence < ctx.min_confidence_threshold:
        return RiskRuleOutcome(
            rule="min_confidence_threshold",
            verdict=RiskVerdict.REJECT,
            passed=False,
            detail=(
                f"Trade confidence {ctx.trade_confidence} below threshold "
                f"{ctx.min_confidence_threshold}"
            ),
        )
    return RiskRuleOutcome(
        rule="min_confidence_threshold", verdict=RiskVerdict.ALLOW, passed=True, detail="ok"
    )


def _rule_abnormal_volatility(ctx: RiskContext) -> RiskRuleOutcome:
    if abs(ctx.volatility_zscore) > ctx.abnormal_volatility_zscore_threshold:
        return RiskRuleOutcome(
            rule="abnormal_volatility",
            verdict=RiskVerdict.REQUIRE_HUMAN,
            passed=False,
            detail=(
                f"Volatility z-score {ctx.volatility_zscore} exceeds threshold "
                f"{ctx.abnormal_volatility_zscore_threshold}; human approval required."
            ),
        )
    return RiskRuleOutcome(rule="abnormal_volatility", verdict=RiskVerdict.ALLOW, passed=True, detail="ok")


# Order matters: this is the exact rule chain from docs/risk-framework.md. The first
# failing rule short-circuits the remaining checks.
RULE_CHAIN: list = [
    _rule_trading_halted,
    _rule_data_freshness,
    _rule_critical_provider,
    _rule_position_size,
    _rule_daily_loss,
    _rule_drawdown,
    _rule_strategy_approved,
    _rule_model_version_approved,
    _rule_confidence_threshold,
    _rule_abnormal_volatility,
]


class RiskGovernor:
    """Stateless evaluator. Construct once, call `evaluate()` per trade idea."""

    version = GOVERNOR_VERSION

    def evaluate(self, ctx: RiskContext) -> RiskCheckResult:
        results: list[RiskRuleOutcome] = []
        for rule in RULE_CHAIN:
            outcome = rule(ctx)
            results.append(outcome)
            if not outcome.passed:
                return RiskCheckResult(
                    trade_id=ctx.trade.trade_id,
                    verdict=outcome.verdict,
                    rule_results=results,
                    governor_version=self.version,
                )
        return RiskCheckResult(
            trade_id=ctx.trade.trade_id,
            verdict=RiskVerdict.ALLOW,
            rule_results=results,
            governor_version=self.version,
        )

    def evaluate_fail_closed(self, ctx: RiskContext | None) -> RiskCheckResult:
        """Wraps `evaluate()` so that ANY unexpected failure — a bad context, an
        exception inside a rule, or the governor being unreachable in a distributed
        deployment — resolves to BLOCK rather than silently allowing a trade through.
        `services/risk` is the only code path permitted to call this with `ctx=None`
        (representing "governor service unavailable"); every other caller should
        always have a fully-constructed context.
        """
        if ctx is None:
            return RiskCheckResult(
                trade_id=_NIL_TRADE_ID,
                verdict=RiskVerdict.BLOCK,
                rule_results=[
                    RiskRuleOutcome(
                        rule="governor_availability",
                        verdict=RiskVerdict.BLOCK,
                        passed=False,
                        detail="Risk Governor context unavailable; failing closed.",
                    )
                ],
                governor_version=self.version,
            )
        try:
            return self.evaluate(ctx)
        except Exception as exc:  # pragma: no cover - defensive fail-closed path
            return RiskCheckResult(
                trade_id=ctx.trade.trade_id,
                verdict=RiskVerdict.BLOCK,
                rule_results=[
                    RiskRuleOutcome(
                        rule="governor_exception",
                        verdict=RiskVerdict.BLOCK,
                        passed=False,
                        detail=f"Risk Governor raised {type(exc).__name__}: {exc}; failing closed.",
                    )
                ],
                governor_version=self.version,
            )
