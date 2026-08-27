"""`BriefEngine` (docs/alpha-intelligence.md section 10, Milestone 7): composes
the Overnight Intelligence Brief from already-computed, already-persisted
records. Pure, template-based -- no LLM."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from alpha_service import BriefEngine
from schemas import (
    ConsensusView,
    LessonProposal,
    LessonProposalStatus,
    ScenarioRunResult,
    Signal,
    SignalDirection,
    SignalType,
)

PERIOD_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
PERIOD_END = datetime(2026, 1, 2, tzinfo=timezone.utc)


def make_signal(headline: str, materiality: float) -> Signal:
    return Signal(
        signal_type=SignalType.STORAGE_CHANGE,
        category="STORAGE",
        headline=headline,
        description="d",
        materiality_score=materiality,
        confidence=0.7,
        direction=SignalDirection.BULLISH,
    )


def test_compose_with_no_data_is_honest_about_emptiness():
    brief = BriefEngine().compose(
        market="HENRY_HUB",
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        signals=[],
        impacts=[],
        consensus_views=[],
        scenario_runs=[],
        lesson_proposals=[],
    )

    assert brief.headline == "No material signals or consensus divergence in this period."
    assert "No material signals detected" in brief.summary
    assert brief.top_signals == []


def test_top_signals_ranked_by_materiality_and_capped_at_top_n():
    signals = [make_signal(f"signal-{i}", materiality) for i, materiality in enumerate([60, 90, 75, 82, 61, 99])]

    brief = BriefEngine().compose(
        market="HENRY_HUB",
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        signals=signals,
        impacts=[],
        consensus_views=[],
        scenario_runs=[],
        lesson_proposals=[],
        top_n=3,
    )

    assert len(brief.top_signals) == 3
    assert [s.materiality_score for s in brief.top_signals] == [99, 90, 82]
    assert brief.headline.startswith("STORAGE_CHANGE:")


def test_pending_lessons_are_filtered_from_reviewed_ones():
    pending = LessonProposal(
        memory_record_id=uuid4(), proposed_lesson="p", rationale="r", status=LessonProposalStatus.PENDING
    )
    approved = LessonProposal(
        memory_record_id=uuid4(), proposed_lesson="a", rationale="r", status=LessonProposalStatus.APPROVED
    )

    brief = BriefEngine().compose(
        market="HENRY_HUB",
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        signals=[],
        impacts=[],
        consensus_views=[],
        scenario_runs=[],
        lesson_proposals=[pending, approved],
    )

    assert len(brief.pending_lessons) == 1
    assert brief.pending_lessons[0].id == pending.id
    assert "1 lesson proposal(s)" in brief.summary


def test_worst_scenario_run_leads_the_notable_list():
    good = ScenarioRunResult(
        scenario_name="mild", portfolio_pnl=5.0, margin_impact=0.0, var_impact=1.0, largest_risk_contributor="x"
    )
    bad = ScenarioRunResult(
        scenario_name="severe", portfolio_pnl=-50.0, margin_impact=0.0, var_impact=10.0, largest_risk_contributor="y"
    )

    brief = BriefEngine().compose(
        market="HENRY_HUB",
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        signals=[],
        impacts=[],
        consensus_views=[],
        scenario_runs=[good, bad],
        lesson_proposals=[],
    )

    assert brief.notable_scenario_runs[0].scenario_name == "severe"
    assert "severe" in brief.summary


def test_consensus_headline_used_when_no_signals():
    view = ConsensusView(
        consensus_type="MARKET_DIRECTION", target="PRICE", market="HENRY_HUB",
        bull_probability=0.6, bear_probability=0.3, agreement_label="MEDIUM", agent_count=3,
        dispersion=0.4,
    )

    brief = BriefEngine().compose(
        market="HENRY_HUB",
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        signals=[],
        impacts=[],
        consensus_views=[view],
        scenario_runs=[],
        lesson_proposals=[],
    )

    assert brief.headline == "AlphaConsensus: MEDIUM agreement on HENRY_HUB PRICE"
