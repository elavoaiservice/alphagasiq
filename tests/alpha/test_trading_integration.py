"""`AlphaCorroborationEngine` (docs/alpha-intelligence.md section 10, Milestone 7):
the first Alpha* integration point that feeds real Alpha Intelligence Layer output
back into trade evaluation, cross-checking a `TradeIdea` against fresh AlphaSignal
output and the latest AlphaConsensus view before the Investment Committee ever
sees it."""

from __future__ import annotations

from alpha_service import AlphaCorroborationEngine
from alpha_service.materiality import DEFAULT_MATERIALITY_THRESHOLD
from schemas import ConsensusView, Direction, InstrumentType, Signal, SignalDirection, SignalType, TradeIdea


def make_trade(direction: Direction = Direction.LONG) -> TradeIdea:
    return TradeIdea(
        strategy="TEST",
        instrument="NG.FUT.M1",
        instrument_type=InstrumentType.FUTURE,
        direction=direction,
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


def make_signal(
    materiality_score: float = 75.0, direction: SignalDirection = SignalDirection.BULLISH
) -> Signal:
    return Signal(
        signal_type=SignalType.WEATHER_CHANGE,
        category="WEATHER",
        headline="Cold snap forming",
        description="d",
        materiality_score=materiality_score,
        confidence=0.8,
        direction=direction,
    )


def make_consensus_view(bull: float = 0.7, bear: float = 0.2, dissenting: list[str] | None = None) -> ConsensusView:
    return ConsensusView(
        consensus_type="MARKET_DIRECTION",
        target="PRICE",
        bull_probability=bull,
        bear_probability=bear,
        agreement_label="HIGH",
        agent_count=4,
        dissenting_agents=dissenting or [],
    )


def test_aligned_signal_becomes_a_catalyst():
    engine = AlphaCorroborationEngine()
    trade = make_trade(Direction.LONG)
    sig = make_signal(direction=SignalDirection.BULLISH)

    result = engine.corroborate(trade=trade, signals=[sig], consensus_view=None)

    assert len(result.additional_catalysts) == 1
    assert "Cold snap forming" in result.additional_catalysts[0]
    assert result.additional_citations == [f"alpha_signal:{sig.id}"]
    assert result.additional_risks == []


def test_opposed_signal_becomes_a_caution_risk():
    engine = AlphaCorroborationEngine()
    trade = make_trade(Direction.LONG)
    sig = make_signal(direction=SignalDirection.BEARISH)

    result = engine.corroborate(trade=trade, signals=[sig], consensus_view=None)

    assert result.additional_catalysts == []
    assert len(result.additional_risks) == 1
    assert "caution" in result.additional_risks[0].lower()


def test_neutral_signal_is_never_scored():
    engine = AlphaCorroborationEngine()
    trade = make_trade(Direction.LONG)
    sig = make_signal(direction=SignalDirection.NEUTRAL)

    result = engine.corroborate(trade=trade, signals=[sig], consensus_view=None)

    assert result.is_empty


def test_below_threshold_signal_is_ignored():
    engine = AlphaCorroborationEngine()
    trade = make_trade(Direction.LONG)
    sig = make_signal(materiality_score=DEFAULT_MATERIALITY_THRESHOLD - 1, direction=SignalDirection.BULLISH)

    result = engine.corroborate(trade=trade, signals=[sig], consensus_view=None)

    assert result.is_empty


def test_spread_trade_never_scores_signals_or_consensus():
    engine = AlphaCorroborationEngine()
    trade = make_trade(Direction.SPREAD)
    sig = make_signal(direction=SignalDirection.BULLISH)
    view = make_consensus_view(bull=0.9, bear=0.05)

    result = engine.corroborate(trade=trade, signals=[sig], consensus_view=view)

    assert result.is_empty


def test_agreeing_consensus_becomes_supporting_data():
    engine = AlphaCorroborationEngine()
    trade = make_trade(Direction.LONG)
    view = make_consensus_view(bull=0.7, bear=0.2)

    result = engine.corroborate(trade=trade, signals=[], consensus_view=view)

    assert len(result.additional_supporting_data) == 1
    assert "AlphaConsensus agrees" in result.additional_supporting_data[0]
    assert result.additional_risks == []


def test_dissenting_consensus_becomes_a_caution_risk_with_dissenters_named():
    engine = AlphaCorroborationEngine()
    trade = make_trade(Direction.LONG)
    view = make_consensus_view(bull=0.2, bear=0.7, dissenting=["STORAGE", "WEATHER"])

    result = engine.corroborate(trade=trade, signals=[], consensus_view=view)

    assert result.additional_supporting_data == []
    assert len(result.additional_risks) == 1
    assert "STORAGE" in result.additional_risks[0]
    assert "WEATHER" in result.additional_risks[0]


def test_short_trade_direction_alignment_is_mirrored():
    engine = AlphaCorroborationEngine()
    trade = make_trade(Direction.SHORT)
    sig = make_signal(direction=SignalDirection.BEARISH)
    view = make_consensus_view(bull=0.2, bear=0.7)

    result = engine.corroborate(trade=trade, signals=[sig], consensus_view=view)

    assert len(result.additional_catalysts) == 1
    assert len(result.additional_supporting_data) == 1
    assert result.additional_risks == []


def test_nothing_matching_is_empty():
    engine = AlphaCorroborationEngine()
    trade = make_trade(Direction.LONG)

    result = engine.corroborate(trade=trade, signals=[], consensus_view=None)

    assert result.is_empty
