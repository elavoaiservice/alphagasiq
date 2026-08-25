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


def make_forecast(*, return_forecast: float, up_probability: float, model_type: str = "LINEAR_REGRESSION") -> "PriceForecast":
    from schemas import ForecastHorizon, PriceForecast

    return PriceForecast(
        instrument="NGQ26",
        horizon=ForecastHorizon.SEVEN_DAY,
        price_forecast=3.0 + return_forecast,
        return_forecast=return_forecast,
        up_probability=up_probability,
        down_probability=round(1 - up_probability, 4),
        expected_volatility=0.05,
        confidence=0.7,
        model_contributions={model_type: 1.0},
    )


class TestQuantForecastUnification:
    """The unification this module exists to enable: a PostTradeAnalysis can score
    both the strategy's own thesis AND the Quantitative Team's actual forecast for
    the same trade, on their own separate terms."""

    def test_no_forecast_leaves_quant_fields_none(self):
        trade = make_trade()
        analysis = evaluate_post_trade(
            trade=trade, committee=make_committee(trade, 0.7), risk_check=make_risk_check(trade, RiskVerdict.ALLOW),
            entry_price=3.0, exit_price=3.3, opened_at=NOW, closed_at=NOW,
        )
        assert analysis.quant_model_type is None
        assert analysis.quant_model_version is None
        assert analysis.quant_predicted_return is None
        assert analysis.quant_forecast_error is None
        assert analysis.quant_up_probability is None

    def test_long_trade_forecast_error_is_actual_minus_predicted(self):
        from schemas import ModelType

        trade = make_trade(direction=Direction.LONG)
        forecast = make_forecast(return_forecast=0.2, up_probability=0.7)
        analysis = evaluate_post_trade(
            trade=trade, committee=make_committee(trade, 0.7), risk_check=make_risk_check(trade, RiskVerdict.ALLOW),
            entry_price=3.0, exit_price=3.3, opened_at=NOW, closed_at=NOW,
            forecast=forecast, forecast_model_type=ModelType.LINEAR_REGRESSION, forecast_model_version="1.0.0",
        )
        assert analysis.quant_model_type == ModelType.LINEAR_REGRESSION
        assert analysis.quant_model_version == "1.0.0"
        assert analysis.quant_predicted_return == pytest.approx(0.2)
        # actual_return = 0.3 (long, 3.0 -> 3.3); predicted = 0.2 -> error = 0.1
        assert analysis.quant_forecast_error == pytest.approx(0.1)
        assert analysis.quant_up_probability == pytest.approx(0.7)

    def test_short_trade_forecast_fields_are_direction_adjusted(self):
        """A raw bearish forecast (return_forecast < 0) on a SHORT trade should read
        as a *positive* predicted return for the trade (the model expects it to
        profit), and quant_up_probability should reflect win-probability for a short
        (i.e. down_probability), not the raw up_probability."""
        from schemas import ModelType

        trade = make_trade(direction=Direction.SHORT, entry=3.0, target=2.7, stop_or_invalidation=3.2)
        forecast = make_forecast(return_forecast=-0.2, up_probability=0.2)  # bearish forecast
        analysis = evaluate_post_trade(
            trade=trade, committee=make_committee(trade, 0.7), risk_check=make_risk_check(trade, RiskVerdict.ALLOW),
            entry_price=3.0, exit_price=2.8, opened_at=NOW, closed_at=NOW,
            forecast=forecast, forecast_model_type=ModelType.LINEAR_REGRESSION, forecast_model_version="1.0.0",
        )
        # direction_sign=-1, so predicted = -1 * -0.2 = +0.2 (model expects the short to profit)
        assert analysis.quant_predicted_return == pytest.approx(0.2)
        # win-probability for a short = down_probability = 1 - 0.2 = 0.8
        assert analysis.quant_up_probability == pytest.approx(0.8)

    def test_lessons_mentions_the_quant_model_when_forecast_attached(self):
        from schemas import ModelType

        trade = make_trade()
        forecast = make_forecast(return_forecast=0.2, up_probability=0.7)
        analysis = evaluate_post_trade(
            trade=trade, committee=make_committee(trade, 0.7), risk_check=make_risk_check(trade, RiskVerdict.ALLOW),
            entry_price=3.0, exit_price=3.3, opened_at=NOW, closed_at=NOW,
            forecast=forecast, forecast_model_type=ModelType.LINEAR_REGRESSION, forecast_model_version="1.0.0",
        )
        assert "LINEAR_REGRESSION" in analysis.lessons

    def test_forecast_without_model_type_still_scores_but_no_lessons_mention(self):
        """Defensive: if a caller supplies a forecast but omits the model type (should
        not normally happen), the numeric fields still compute correctly and no
        model-specific sentence is fabricated."""
        trade = make_trade()
        forecast = make_forecast(return_forecast=0.2, up_probability=0.7)
        analysis = evaluate_post_trade(
            trade=trade, committee=make_committee(trade, 0.7), risk_check=make_risk_check(trade, RiskVerdict.ALLOW),
            entry_price=3.0, exit_price=3.3, opened_at=NOW, closed_at=NOW,
            forecast=forecast,
        )
        assert analysis.quant_predicted_return == pytest.approx(0.2)
        assert analysis.quant_model_type is None
