"""tests/alpha/test_memory_builder.py -- AlphaMemory(TM)'s MemoryBuilder/LessonEngine.
Table-driven, mirroring test_agent_alpha_score.py's style: one class per invariant,
plus the four OutcomeQuadrant lesson templates."""

from __future__ import annotations

import pytest
from alpha_service.memory_builder import LessonEngine, MemoryBuilder
from schemas import (
    Direction,
    InstrumentType,
    InvestmentCommitteeDecision,
    MemoryType,
    OutcomeQuadrant,
    PostTradeAnalysis,
    PriceForecast,
    RecommendedAction,
    RiskCheckResult,
    RiskVerdict,
    TradeIdea,
)


def make_trade(**overrides) -> TradeIdea:
    defaults = dict(
        strategy="DIRECTIONAL",
        instrument="NG_M1",
        instrument_type=InstrumentType.FUTURE,
        direction=Direction.LONG,
        entry=3.0,
        target=3.5,
        stop_or_invalidation=2.8,
        time_horizon="1W",
        expected_return=0.5,
        expected_loss=0.2,
        probability_success=0.6,
        confidence=0.7,
        thesis="cold winter",
    )
    defaults.update(overrides)
    return TradeIdea(**defaults)


def make_committee(trade: TradeIdea, **overrides) -> InvestmentCommitteeDecision:
    defaults = dict(
        original_trade=trade,
        bull_case="b",
        bear_case="c",
        skeptic_case="d",
        data_quality_assessment="ok",
        portfolio_effect="ok",
        consensus_score=0.8,
        recommended_action=RecommendedAction.APPROVE_FOR_REVIEW,
    )
    defaults.update(overrides)
    return InvestmentCommitteeDecision(**defaults)


def make_risk_check(trade: TradeIdea, verdict: RiskVerdict = RiskVerdict.ALLOW) -> RiskCheckResult:
    return RiskCheckResult(trade_id=trade.trade_id, verdict=verdict, rule_results=[], governor_version="1.0")


def make_post_trade(trade: TradeIdea, quadrant: OutcomeQuadrant, **overrides) -> PostTradeAnalysis:
    defaults = dict(
        trade_id=trade.trade_id,
        thesis_accuracy=0.9,
        timing_accuracy=1.0,
        risk_accuracy=1.0,
        lessons="Thesis was directionally correct.",
        quadrant=quadrant,
    )
    defaults.update(overrides)
    return PostTradeAnalysis(**defaults)


@pytest.fixture
def builder() -> MemoryBuilder:
    return MemoryBuilder()


@pytest.fixture
def lesson_engine() -> LessonEngine:
    return LessonEngine()


class TestBuildDecisionMemory:
    def test_memory_is_decision_type_linked_to_trade(self, builder):
        trade = make_trade()
        committee = make_committee(trade)
        risk_check = make_risk_check(trade)
        post_trade = make_post_trade(trade, OutcomeQuadrant.GOOD_DECISION_GOOD_OUTCOME)

        memory = builder.build_decision_memory(
            trade=trade, committee=committee, risk_check=risk_check, post_trade=post_trade
        )
        assert memory.memory_type == MemoryType.DECISION_MEMORY
        assert memory.trade_id == trade.trade_id
        assert memory.market == trade.instrument
        assert memory.strategy == trade.strategy
        assert memory.outcome_quadrant == OutcomeQuadrant.GOOD_DECISION_GOOD_OUTCOME

    def test_summary_carries_forward_post_trade_lessons_verbatim(self, builder):
        trade = make_trade()
        committee = make_committee(trade)
        risk_check = make_risk_check(trade)
        post_trade = make_post_trade(
            trade, OutcomeQuadrant.BAD_DECISION_BAD_OUTCOME, lessons="a specific lessons string"
        )
        memory = builder.build_decision_memory(
            trade=trade, committee=committee, risk_check=risk_check, post_trade=post_trade
        )
        assert memory.summary == "a specific lessons string"

    def test_structured_context_includes_committee_and_risk_and_accuracy_figures(self, builder):
        trade = make_trade()
        committee = make_committee(trade, consensus_score=0.55)
        risk_check = make_risk_check(trade, verdict=RiskVerdict.BLOCK)
        post_trade = make_post_trade(trade, OutcomeQuadrant.BAD_DECISION_GOOD_OUTCOME)
        memory = builder.build_decision_memory(
            trade=trade, committee=committee, risk_check=risk_check, post_trade=post_trade
        )
        assert memory.structured_context["committee_consensus_score"] == 0.55
        assert memory.structured_context["risk_verdict"] == "BLOCK"
        assert memory.structured_context["thesis_accuracy"] == post_trade.thesis_accuracy
        assert "quant_forecast" not in memory.structured_context

    def test_forecast_is_included_when_attached(self, builder):
        trade = make_trade()
        committee = make_committee(trade)
        risk_check = make_risk_check(trade)
        post_trade = make_post_trade(trade, OutcomeQuadrant.GOOD_DECISION_GOOD_OUTCOME)
        forecast = PriceForecast(
            instrument="NG_M1",
            horizon="7d",
            price_forecast=3.2,
            return_forecast=0.05,
            up_probability=0.65,
            down_probability=0.35,
            expected_volatility=0.2,
            confidence=0.7,
        )
        memory = builder.build_decision_memory(
            trade=trade, committee=committee, risk_check=risk_check, post_trade=post_trade, forecast=forecast
        )
        assert memory.structured_context["quant_forecast"]["up_probability"] == 0.65

    def test_organization_id_is_carried_forward(self, builder):
        trade = make_trade()
        committee = make_committee(trade)
        risk_check = make_risk_check(trade)
        post_trade = make_post_trade(trade, OutcomeQuadrant.GOOD_DECISION_GOOD_OUTCOME)
        memory = builder.build_decision_memory(
            trade=trade, committee=committee, risk_check=risk_check, post_trade=post_trade, organization_id="org-1"
        )
        assert memory.organization_id == "org-1"


class TestLessonEngine:
    @pytest.mark.parametrize(
        "quadrant",
        [
            OutcomeQuadrant.GOOD_DECISION_GOOD_OUTCOME,
            OutcomeQuadrant.GOOD_DECISION_BAD_OUTCOME,
            OutcomeQuadrant.BAD_DECISION_GOOD_OUTCOME,
            OutcomeQuadrant.BAD_DECISION_BAD_OUTCOME,
        ],
    )
    def test_every_quadrant_produces_a_distinct_lesson(self, builder, lesson_engine, quadrant):
        trade = make_trade()
        committee = make_committee(trade)
        risk_check = make_risk_check(trade)
        post_trade = make_post_trade(trade, quadrant)
        memory = builder.build_decision_memory(
            trade=trade, committee=committee, risk_check=risk_check, post_trade=post_trade
        )
        lesson = lesson_engine.propose(memory)
        assert lesson is not None
        assert lesson.memory_record_id == memory.id
        assert lesson.proposed_lesson

    def test_lesson_starts_pending(self, builder, lesson_engine):
        trade = make_trade()
        committee = make_committee(trade)
        risk_check = make_risk_check(trade)
        post_trade = make_post_trade(trade, OutcomeQuadrant.GOOD_DECISION_GOOD_OUTCOME)
        memory = builder.build_decision_memory(
            trade=trade, committee=committee, risk_check=risk_check, post_trade=post_trade
        )
        lesson = lesson_engine.propose(memory)
        assert lesson.status.value == "PENDING"
        assert lesson.reviewed_by is None
        assert lesson.reviewed_at is None

    def test_no_outcome_quadrant_yields_no_lesson(self, lesson_engine):
        from schemas import MemoryRecord

        memory = MemoryRecord(title="t", summary="s", outcome_quadrant=None)
        assert lesson_engine.propose(memory) is None

    def test_good_and_bad_decision_lessons_differ(self, builder, lesson_engine):
        trade = make_trade()
        committee = make_committee(trade)
        risk_check = make_risk_check(trade)
        good = lesson_engine.propose(
            builder.build_decision_memory(
                trade=trade,
                committee=committee,
                risk_check=risk_check,
                post_trade=make_post_trade(trade, OutcomeQuadrant.GOOD_DECISION_BAD_OUTCOME),
            )
        )
        bad = lesson_engine.propose(
            builder.build_decision_memory(
                trade=trade,
                committee=committee,
                risk_check=risk_check,
                post_trade=make_post_trade(trade, OutcomeQuadrant.BAD_DECISION_BAD_OUTCOME),
            )
        )
        assert good.proposed_lesson != bad.proposed_lesson
