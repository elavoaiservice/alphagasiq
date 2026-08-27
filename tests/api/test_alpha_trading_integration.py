"""Milestone 7 (docs/alpha-intelligence.md section 10): `AppState.submit_trade_idea()`
is the single choke point every trade idea passes through before the Investment
Committee deliberates -- this is where AlphaSignal/AlphaConsensus output gets
merged onto the trade's own `catalysts`/`supporting_data`/`source_citations`/
`risks` fields, closing the loop that every other Alpha* component (which only
runs downstream of trade generation) never does."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from schemas import ConsensusView, Direction, InstrumentType, Signal, SignalDirection, SignalType, TradeIdea


@pytest.fixture
def client():
    from api_app import state as state_module

    state_module.reset_app_state()
    from api_app.main import app

    with TestClient(app) as c:
        yield c
    state_module.reset_app_state()


def _make_trade(instrument: str) -> TradeIdea:
    return TradeIdea(
        strategy="TEST_CORROBORATION",
        instrument=instrument,
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
        thesis="test thesis",
    )


async def test_submit_trade_idea_attaches_aligned_signal_as_a_catalyst(client):
    from api_app import state as state_module

    state = state_module._state
    trade = _make_trade(state.primary_instrument())
    state.recent_signals = [
        Signal(
            signal_type=SignalType.WEATHER_CHANGE,
            category="WEATHER",
            headline="Severe cold snap forming",
            description="d",
            materiality_score=80,
            confidence=0.8,
            direction=SignalDirection.BULLISH,
        )
    ]

    await state.submit_trade_idea(trade)

    stored = state.trade_ideas[trade.trade_id]
    assert any("Severe cold snap forming" in c for c in stored.catalysts)
    assert any(c.startswith("alpha_signal:") for c in stored.source_citations)


async def test_submit_trade_idea_attaches_opposed_signal_as_a_risk(client):
    from api_app import state as state_module

    state = state_module._state
    trade = _make_trade(state.primary_instrument())
    state.recent_signals = [
        Signal(
            signal_type=SignalType.STORAGE_CHANGE,
            category="STORAGE",
            headline="Storage build far above expectations",
            description="d",
            materiality_score=85,
            confidence=0.8,
            direction=SignalDirection.BEARISH,
        )
    ]

    await state.submit_trade_idea(trade)

    stored = state.trade_ideas[trade.trade_id]
    assert any("Storage build far above expectations" in r for r in stored.risks)
    assert stored.catalysts == []


async def test_submit_trade_idea_attaches_agreeing_consensus_as_supporting_data(client):
    from api_app import state as state_module

    state = state_module._state
    trade = _make_trade(state.primary_instrument())
    state.recent_consensus_views = [
        ConsensusView(
            consensus_type="MARKET_DIRECTION",
            target="PRICE",
            bull_probability=0.75,
            bear_probability=0.15,
            agreement_label="HIGH",
            agent_count=5,
        )
    ]

    await state.submit_trade_idea(trade)

    stored = state.trade_ideas[trade.trade_id]
    assert any("AlphaConsensus agrees" in s for s in stored.supporting_data)


async def test_submit_trade_idea_with_no_alpha_data_leaves_trade_unchanged(client):
    from api_app import state as state_module

    state = state_module._state
    state.recent_signals = []
    state.recent_consensus_views = []
    trade = _make_trade(state.primary_instrument())

    await state.submit_trade_idea(trade)

    stored = state.trade_ideas[trade.trade_id]
    assert stored.catalysts == []
    assert stored.risks == []
    assert stored.supporting_data == []
    assert stored.source_citations == []
