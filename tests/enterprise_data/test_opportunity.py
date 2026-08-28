"""Opportunity Engine (docs/alpha-intelligence.md section 11.7, Milestone 10):
`EnterpriseOpportunityEngine` -- pure cross-referencing of an organization's own
proprietary position data against Alpha Intelligence signals/consensus."""

from __future__ import annotations

from enterprise_data_service.opportunity import EnterpriseOpportunityEngine, EnterprisePosition
from schemas import ConsensusView, Signal, SignalDirection, SignalType


def _consensus(**overrides) -> ConsensusView:
    defaults = dict(
        consensus_type="PRICE",
        market="HENRY_HUB",
        target="price",
        bull_probability=0.1,
        bear_probability=0.8,
        confidence=0.75,
        agreement_label="HIGH",
        agent_count=5,
    )
    defaults.update(overrides)
    return ConsensusView(**defaults)


def _signal(**overrides) -> Signal:
    defaults = dict(
        signal_type=SignalType.STORAGE_CHANGE,
        category="fundamentals",
        headline="big draw",
        description="d",
        materiality_score=90.0,
        confidence=0.85,
        direction=SignalDirection.BULLISH,
        market="HENRY_HUB",
    )
    defaults.update(overrides)
    return Signal(**defaults)


def test_long_position_misaligned_with_bearish_consensus_generates_hedge_candidate():
    engine = EnterpriseOpportunityEngine()
    pos = EnterprisePosition(dataset_id="d1", record_id="r1", market="HENRY_HUB", direction="LONG")
    out = engine.generate(positions=[pos], signals=[], consensus_views=[_consensus()])
    assert len(out) == 1
    assert out[0].opportunity_type == "HEDGE_MISALIGNED_POSITION"
    assert out[0].related_record_id == "r1"


def test_short_position_misaligned_with_bullish_consensus_generates_hedge_candidate():
    engine = EnterpriseOpportunityEngine()
    pos = EnterprisePosition(dataset_id="d1", record_id="r1", market="HENRY_HUB", direction="SHORT")
    out = engine.generate(
        positions=[pos], signals=[], consensus_views=[_consensus(bull_probability=0.8, bear_probability=0.1)]
    )
    assert len(out) == 1
    assert out[0].opportunity_type == "HEDGE_MISALIGNED_POSITION"


def test_aligned_position_generates_no_hedge_candidate():
    engine = EnterpriseOpportunityEngine()
    pos = EnterprisePosition(dataset_id="d1", record_id="r1", market="HENRY_HUB", direction="SHORT")
    out = engine.generate(positions=[pos], signals=[], consensus_views=[_consensus()])
    assert out == []


def test_low_confidence_consensus_does_not_generate_hedge_candidate():
    engine = EnterpriseOpportunityEngine()
    pos = EnterprisePosition(dataset_id="d1", record_id="r1", market="HENRY_HUB", direction="LONG")
    out = engine.generate(positions=[pos], signals=[], consensus_views=[_consensus(confidence=0.3)])
    assert out == []


def test_weak_divergence_consensus_does_not_generate_hedge_candidate():
    engine = EnterpriseOpportunityEngine()
    pos = EnterprisePosition(dataset_id="d1", record_id="r1", market="HENRY_HUB", direction="LONG")
    out = engine.generate(
        positions=[pos], signals=[], consensus_views=[_consensus(bull_probability=0.45, bear_probability=0.55)]
    )
    assert out == []


def test_high_conviction_signal_with_no_position_generates_new_position_candidate():
    engine = EnterpriseOpportunityEngine()
    out = engine.generate(positions=[], signals=[_signal()], consensus_views=[])
    assert len(out) == 1
    assert out[0].opportunity_type == "NEW_POSITION_HIGH_CONVICTION_SIGNAL"
    assert out[0].market == "HENRY_HUB"


def test_signal_in_a_market_with_an_existing_position_generates_no_new_position_candidate():
    engine = EnterpriseOpportunityEngine()
    pos = EnterprisePosition(dataset_id="d1", record_id="r1", market="HENRY_HUB", direction="LONG")
    out = engine.generate(positions=[pos], signals=[_signal()], consensus_views=[])
    assert out == []


def test_low_materiality_signal_generates_no_candidate():
    engine = EnterpriseOpportunityEngine()
    out = engine.generate(positions=[], signals=[_signal(materiality_score=40.0)], consensus_views=[])
    assert out == []


def test_neutral_signal_generates_no_candidate():
    engine = EnterpriseOpportunityEngine()
    out = engine.generate(positions=[], signals=[_signal(direction=SignalDirection.NEUTRAL)], consensus_views=[])
    assert out == []


def test_from_record_parses_market_direction_quantity():
    pos = EnterprisePosition.from_record(
        dataset_id="d1", record_id="r1", row_data={"market": "HENRY_HUB", "direction": "long", "quantity": 100}
    )
    assert pos is not None
    assert pos.market == "HENRY_HUB"
    assert pos.direction == "LONG"
    assert pos.quantity == 100


def test_from_record_accepts_instrument_as_market_alias():
    pos = EnterprisePosition.from_record(dataset_id="d1", record_id="r1", row_data={"instrument": "WAHA"})
    assert pos is not None
    assert pos.market == "WAHA"


def test_from_record_returns_none_when_market_missing():
    assert EnterprisePosition.from_record(dataset_id="d1", record_id="r1", row_data={"direction": "LONG"}) is None


def test_from_record_ignores_invalid_direction_and_quantity():
    pos = EnterprisePosition.from_record(
        dataset_id="d1", record_id="r1", row_data={"market": "HENRY_HUB", "direction": "SIDEWAYS", "quantity": "lots"}
    )
    assert pos is not None
    assert pos.direction is None
    assert pos.quantity is None
