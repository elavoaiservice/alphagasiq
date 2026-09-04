"""High-coverage tests for the deterministic Risk Governor.

Per docs/risk-framework.md: "No LLM may override a failed hard risk rule" and
"Critical risk logic must have extremely high test coverage." Every rule in the chain
gets at least one test proving it blocks/halts/rejects as specified, plus tests for
rule ordering (short-circuit) and the fail-closed wrapper.
"""

from __future__ import annotations

import pytest
from risk_service.governor import RiskContext, RiskGovernor
from risk_service.limits import default_risk_limits
from schemas import Direction, InstrumentType, RiskVerdict, TradeIdea


def make_trade(**overrides) -> TradeIdea:
    defaults = dict(
        strategy="directional",
        instrument="NGZ26",
        instrument_type=InstrumentType.FUTURE,
        direction=Direction.LONG,
        entry=3.0,
        target=3.5,
        stop_or_invalidation=2.8,
        time_horizon="2W",
        expected_return=5000,
        expected_loss=2000,
        probability_success=0.6,
        confidence=0.7,
        thesis="test thesis",
    )
    defaults.update(overrides)
    return TradeIdea(**defaults)


def make_ctx(**overrides) -> RiskContext:
    defaults = dict(
        trade=make_trade(),
        limits=default_risk_limits(),
        proposed_position_size=1000,
    )
    defaults.update(overrides)
    return RiskContext(**defaults)


@pytest.fixture
def governor() -> RiskGovernor:
    return RiskGovernor()


class TestAllowPath:
    def test_clean_trade_is_allowed(self, governor):
        result = governor.evaluate(make_ctx())
        assert result.verdict == RiskVerdict.ALLOW
        assert all(r.passed for r in result.rule_results)
        assert result.blocking_rule is None


class TestEachRuleBlocks:
    def test_trading_halted_halts(self, governor):
        result = governor.evaluate(make_ctx(trading_halted=True))
        assert result.verdict == RiskVerdict.HALT
        assert result.blocking_rule.rule == "trading_halted"

    def test_stale_data_blocks(self, governor):
        result = governor.evaluate(
            make_ctx(required_data_is_fresh=False, stale_sources=["EIA"])
        )
        assert result.verdict == RiskVerdict.BLOCK
        assert result.blocking_rule.rule == "data_freshness"

    def test_critical_provider_unavailable_blocks_by_default(self, governor):
        result = governor.evaluate(
            make_ctx(critical_provider_available=False, unavailable_providers=["mock_cme"])
        )
        assert result.verdict == RiskVerdict.BLOCK
        assert result.blocking_rule.rule == "critical_provider_availability"

    def test_critical_provider_unavailable_can_require_human(self, governor):
        result = governor.evaluate(
            make_ctx(
                critical_provider_available=False,
                on_critical_provider_unavailable=RiskVerdict.REQUIRE_HUMAN,
            )
        )
        assert result.verdict == RiskVerdict.REQUIRE_HUMAN

    def test_position_size_over_limit_blocks(self, governor):
        limits = default_risk_limits()
        result = governor.evaluate(
            make_ctx(limits=limits, proposed_position_size=limits.max_position_size + 1)
        )
        assert result.verdict == RiskVerdict.BLOCK
        assert result.blocking_rule.rule == "max_position_size"

    def test_risk_per_trade_over_limit_blocks(self, governor):
        limits = default_risk_limits()
        huge_stop_distance_trade = make_trade(entry=3.0, stop_or_invalidation=0.0)
        result = governor.evaluate(
            make_ctx(
                trade=huge_stop_distance_trade,
                limits=limits,
                proposed_position_size=limits.max_position_size,
            )
        )
        assert result.verdict == RiskVerdict.BLOCK
        assert result.blocking_rule.rule == "max_risk_per_trade"

    def test_daily_loss_limit_blocks_new_risk(self, governor):
        limits = default_risk_limits()
        result = governor.evaluate(
            make_ctx(limits=limits, current_daily_loss=limits.max_daily_loss)
        )
        assert result.verdict == RiskVerdict.BLOCK_NEW_RISK
        assert result.blocking_rule.rule == "max_daily_loss"

    def test_drawdown_limit_halts(self, governor):
        limits = default_risk_limits()
        result = governor.evaluate(
            make_ctx(limits=limits, current_drawdown=limits.max_drawdown)
        )
        assert result.verdict == RiskVerdict.HALT
        assert result.blocking_rule.rule == "max_drawdown"

    def test_unapproved_strategy_blocks(self, governor):
        result = governor.evaluate(make_ctx(strategy_approved=False))
        assert result.verdict == RiskVerdict.BLOCK
        assert result.blocking_rule.rule == "strategy_approved"

    def test_unapproved_model_version_blocks(self, governor):
        result = governor.evaluate(
            make_ctx(model_version="v0.0.1-unreviewed", approved_model_versions=frozenset({"v1.0.0"}))
        )
        assert result.verdict == RiskVerdict.BLOCK
        assert result.blocking_rule.rule == "model_version_approved"

    def test_approved_model_version_passes(self, governor):
        result = governor.evaluate(
            make_ctx(model_version="v1.0.0", approved_model_versions=frozenset({"v1.0.0"}))
        )
        assert result.verdict == RiskVerdict.ALLOW

    def test_low_confidence_rejects(self, governor):
        result = governor.evaluate(
            make_ctx(trade_confidence=0.1, min_confidence_threshold=0.55)
        )
        assert result.verdict == RiskVerdict.REJECT
        assert result.blocking_rule.rule == "min_confidence_threshold"

    def test_abnormal_volatility_requires_human(self, governor):
        result = governor.evaluate(
            make_ctx(volatility_zscore=5.0, abnormal_volatility_zscore_threshold=3.0)
        )
        assert result.verdict == RiskVerdict.REQUIRE_HUMAN
        assert result.blocking_rule.rule == "abnormal_volatility"


class TestRuleOrderingShortCircuits:
    def test_first_failure_wins_halt_before_block(self, governor):
        """trading_halted is evaluated first, so it should win over a simultaneous
        position-size breach."""
        limits = default_risk_limits()
        result = governor.evaluate(
            make_ctx(
                trading_halted=True,
                limits=limits,
                proposed_position_size=limits.max_position_size + 1,
            )
        )
        assert result.verdict == RiskVerdict.HALT
        assert len(result.rule_results) == 1

    def test_rules_after_failure_are_not_evaluated(self, governor):
        result = governor.evaluate(make_ctx(required_data_is_fresh=False))
        rule_names = [r.rule for r in result.rule_results]
        assert rule_names == ["trading_halted", "data_freshness"]


class TestFailClosed:
    def test_none_context_fails_closed(self, governor):
        result = governor.evaluate_fail_closed(None)
        assert result.verdict == RiskVerdict.BLOCK

    def test_exception_in_rule_fails_closed(self, governor, monkeypatch):
        def boom(ctx):
            raise RuntimeError("simulated failure")

        monkeypatch.setattr("risk_service.governor.RULE_CHAIN", [boom])
        result = governor.evaluate_fail_closed(make_ctx())
        assert result.verdict == RiskVerdict.BLOCK

    def test_healthy_context_still_allows(self, governor):
        result = governor.evaluate_fail_closed(make_ctx())
        assert result.verdict == RiskVerdict.ALLOW


class TestNoLLMOverride:
    def test_governor_has_no_llm_dependency(self):
        """Static guarantee that the governor module never imports an LLM provider —
        a failed hard rule can never be reasoned around."""
        import risk_service.governor as governor_module

        import_lines = [
            line.strip()
            for line in open(governor_module.__file__)
            if line.strip().startswith(("import ", "from "))
        ]
        joined = "\n".join(import_lines).lower()
        assert "agent_sdk" not in joined
        assert "anthropic" not in joined
        assert "llm" not in joined
