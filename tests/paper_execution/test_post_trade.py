from datetime import datetime, timezone

import pytest
from paper_execution_service import evaluate_post_trade
from schemas import (
    Direction,
    InstrumentType,
    InvestmentCommitteeDecision,
    OutcomeQuadrant,
    RecommendedAction,
    RiskCheckResult,
    RiskVerdict,
    TradeIdea,
)


def make_trade(**overrides) -> TradeIdea:
    defaults = dict(
        strategy="directional_test",
        instrument="NGQ26",
        instrument_type=InstrumentType.FUTURE,
        direction=Direction.LONG,
        entry=3.0,
        target=3.3,
        stop_or_invalidation=2.8,
        time_horizon="1W",
        expected_return=0.3,
        expected_loss=0.2,
        probability_success=0.65,
        confidence=0.7,
        thesis="test thesis",
    )
    defaults.update(overrides)
    return TradeIdea(**defaults)


def make_committee(trade: TradeIdea, consensus_score: float) -> InvestmentCommitteeDecision:
    return InvestmentCommitteeDecision(
        original_trade=trade,
        bull_case="b",
        bear_case="b",
        skeptic_case="s",
        data_quality_assessment="ok",
        portfolio_effect="ok",
        consensus_score=consensus_score,
        recommended_action=RecommendedAction.APPROVE_FOR_REVIEW,
    )


def make_risk_check(trade: TradeIdea, verdict: RiskVerdict) -> RiskCheckResult:
    return RiskCheckResult(trade_id=trade.trade_id, verdict=verdict, rule_results=[], governor_version="1.0.0")


NOW = datetime.now(timezone.utc)


class TestQuadrantClassification:
    def test_good_decision_good_outcome(self):
        trade = make_trade()
        analysis = evaluate_post_trade(
            trade=trade,
            committee=make_committee(trade, 0.75),
            risk_check=make_risk_check(trade, RiskVerdict.ALLOW),
            entry_price=3.0,
            exit_price=3.3,
            opened_at=NOW,
            closed_at=NOW,
        )
        assert analysis.quadrant == OutcomeQuadrant.GOOD_DECISION_GOOD_OUTCOME

    def test_good_decision_bad_outcome(self):
        trade = make_trade()
        analysis = evaluate_post_trade(
            trade=trade,
            committee=make_committee(trade, 0.75),
            risk_check=make_risk_check(trade, RiskVerdict.ALLOW),
            entry_price=3.0,
            exit_price=2.9,
            opened_at=NOW,
            closed_at=NOW,
        )
        assert analysis.quadrant == OutcomeQuadrant.GOOD_DECISION_BAD_OUTCOME

    def test_bad_decision_good_outcome(self):
        trade = make_trade()
        analysis = evaluate_post_trade(
            trade=trade,
            committee=make_committee(trade, 0.3),
            risk_check=make_risk_check(trade, RiskVerdict.REQUIRE_HUMAN),
            entry_price=3.0,
            exit_price=3.3,
            opened_at=NOW,
            closed_at=NOW,
        )
        assert analysis.quadrant == OutcomeQuadrant.BAD_DECISION_GOOD_OUTCOME

    def test_bad_decision_bad_outcome(self):
        trade = make_trade()
        analysis = evaluate_post_trade(
            trade=trade,
            committee=make_committee(trade, 0.3),
            risk_check=make_risk_check(trade, RiskVerdict.REQUIRE_HUMAN),
            entry_price=3.0,
            exit_price=2.7,
            opened_at=NOW,
            closed_at=NOW,
        )
        assert analysis.quadrant == OutcomeQuadrant.BAD_DECISION_BAD_OUTCOME

    def test_low_consensus_alone_is_bad_decision_even_if_risk_allowed(self):
        """Decision quality requires BOTH committee consensus and an ALLOW verdict —
        a trade the Risk Governor let through on a thin consensus is still a bad
        decision if it loses."""
        trade = make_trade()
        analysis = evaluate_post_trade(
            trade=trade,
            committee=make_committee(trade, 0.3),
            risk_check=make_risk_check(trade, RiskVerdict.ALLOW),
            entry_price=3.0,
            exit_price=2.7,
            opened_at=NOW,
            closed_at=NOW,
        )
        assert analysis.quadrant == OutcomeQuadrant.BAD_DECISION_BAD_OUTCOME


class TestTimingAccuracy:
    def test_reaching_target_scores_full_timing_accuracy(self):
        trade = make_trade()
        analysis = evaluate_post_trade(
            trade=trade, committee=make_committee(trade, 0.7), risk_check=make_risk_check(trade, RiskVerdict.ALLOW),
            entry_price=3.0, exit_price=3.35, opened_at=NOW, closed_at=NOW,
        )
        assert analysis.timing_accuracy == 1.0

    def test_breaching_stop_scores_low_timing_accuracy(self):
        trade = make_trade()
        analysis = evaluate_post_trade(
            trade=trade, committee=make_committee(trade, 0.7), risk_check=make_risk_check(trade, RiskVerdict.ALLOW),
            entry_price=3.0, exit_price=2.7, opened_at=NOW, closed_at=NOW,
        )
        assert analysis.timing_accuracy == 0.3

    def test_short_trade_stop_breach_uses_correct_direction(self):
        trade = make_trade(direction=Direction.SHORT, entry=3.0, target=2.7, stop_or_invalidation=3.2)
        # exit above stop for a short = breached
        analysis = evaluate_post_trade(
            trade=trade, committee=make_committee(trade, 0.7), risk_check=make_risk_check(trade, RiskVerdict.ALLOW),
            entry_price=3.0, exit_price=3.3, opened_at=NOW, closed_at=NOW,
        )
        assert analysis.timing_accuracy == 0.3


class TestRiskAccuracy:
    def test_profit_is_always_full_risk_accuracy(self):
        trade = make_trade()
        analysis = evaluate_post_trade(
            trade=trade, committee=make_committee(trade, 0.7), risk_check=make_risk_check(trade, RiskVerdict.ALLOW),
            entry_price=3.0, exit_price=3.1, opened_at=NOW, closed_at=NOW,
        )
        assert analysis.risk_accuracy == 1.0

    def test_loss_within_expected_bound_scores_high(self):
        trade = make_trade(expected_loss=0.5)
        analysis = evaluate_post_trade(
            trade=trade, committee=make_committee(trade, 0.7), risk_check=make_risk_check(trade, RiskVerdict.ALLOW),
            entry_price=3.0, exit_price=2.9, opened_at=NOW, closed_at=NOW,
        )
        assert analysis.risk_accuracy == 1.0

    def test_loss_far_exceeding_expected_bound_scores_low(self):
        trade = make_trade(expected_loss=0.1)
        analysis = evaluate_post_trade(
            trade=trade, committee=make_committee(trade, 0.7), risk_check=make_risk_check(trade, RiskVerdict.ALLOW),
            entry_price=3.0, exit_price=2.0, opened_at=NOW, closed_at=NOW,
        )
        assert analysis.risk_accuracy < 0.5


class TestForecastError:
    def test_forecast_error_is_actual_minus_expected(self):
        trade = make_trade(expected_return=0.3)
        analysis = evaluate_post_trade(
            trade=trade, committee=make_committee(trade, 0.7), risk_check=make_risk_check(trade, RiskVerdict.ALLOW),
            entry_price=3.0, exit_price=3.3, opened_at=NOW, closed_at=NOW,
        )
        assert analysis.forecast_error == pytest.approx(0.0, abs=1e-6)

    def test_short_trade_actual_return_sign_flips_correctly(self):
        trade = make_trade(direction=Direction.SHORT, entry=3.0, target=2.7, expected_return=0.3, stop_or_invalidation=3.2)
        analysis = evaluate_post_trade(
            trade=trade, committee=make_committee(trade, 0.7), risk_check=make_risk_check(trade, RiskVerdict.ALLOW),
            entry_price=3.0, exit_price=2.7, opened_at=NOW, closed_at=NOW,
        )
        assert analysis.actual_outcome["actual_return_per_unit"] == pytest.approx(0.3)


def test_lessons_field_is_nonempty_and_no_chain_of_thought_leaks():
    trade = make_trade()
    analysis = evaluate_post_trade(
        trade=trade, committee=make_committee(trade, 0.7), risk_check=make_risk_check(trade, RiskVerdict.ALLOW),
        entry_price=3.0, exit_price=3.3, opened_at=NOW, closed_at=NOW,
    )
    assert len(analysis.lessons) > 0
    dumped = analysis.model_dump()
    assert "chain_of_thought" not in dumped
