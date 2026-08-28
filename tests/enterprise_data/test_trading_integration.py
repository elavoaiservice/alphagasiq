"""`EnterpriseCorroborationEngine` (docs/alpha-intelligence.md section 11, Milestone
10 follow-up): cross-checks a `TradeIdea` against an organization's own
`EnterprisePosition` holdings before the Investment Committee ever sees it --
mirrors `alpha_service.trading_integration.AlphaCorroborationEngine`'s tests
one level down."""

from __future__ import annotations

from enterprise_data_service import EnterpriseCorroborationEngine, EnterprisePosition
from schemas import Direction, InstrumentType, TradeIdea


def make_trade(direction: Direction = Direction.LONG, instrument: str = "NG.FUT.M1") -> TradeIdea:
    return TradeIdea(
        strategy="TEST",
        instrument=instrument,
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


def make_position(
    market: str = "NG.FUT.M1", direction: str | None = "LONG", quantity: float | None = 500.0
) -> EnterprisePosition:
    return EnterprisePosition(
        dataset_id="ds-1", record_id="rec-1", market=market, direction=direction, quantity=quantity
    )


def test_aligned_position_becomes_supporting_data():
    engine = EnterpriseCorroborationEngine()
    trade = make_trade(Direction.LONG)
    pos = make_position(direction="LONG")

    result = engine.corroborate(trade=trade, positions=[pos])

    assert len(result.additional_supporting_data) == 1
    assert "already holds a long position" in result.additional_supporting_data[0]
    assert result.additional_citations == ["enterprise_position:ds-1:rec-1"]
    assert result.additional_risks == []


def test_opposing_position_becomes_a_risk():
    engine = EnterpriseCorroborationEngine()
    trade = make_trade(Direction.LONG)
    pos = make_position(direction="SHORT")

    result = engine.corroborate(trade=trade, positions=[pos])

    assert result.additional_supporting_data == []
    assert len(result.additional_risks) == 1
    assert "opposing short position" in result.additional_risks[0]
    assert result.additional_citations == ["enterprise_position:ds-1:rec-1"]


def test_position_in_a_different_market_is_ignored():
    engine = EnterpriseCorroborationEngine()
    trade = make_trade(Direction.LONG, instrument="NG.FUT.M1")
    pos = make_position(market="WAHA", direction="LONG")

    result = engine.corroborate(trade=trade, positions=[pos])

    assert result.is_empty


def test_position_with_no_recognizable_direction_is_ignored():
    engine = EnterpriseCorroborationEngine()
    trade = make_trade(Direction.LONG)
    pos = make_position(direction=None)

    result = engine.corroborate(trade=trade, positions=[pos])

    assert result.is_empty


def test_spread_trade_never_scores_positions():
    engine = EnterpriseCorroborationEngine()
    trade = make_trade(Direction.SPREAD)
    pos = make_position(direction="LONG")

    result = engine.corroborate(trade=trade, positions=[pos])

    assert result.is_empty


def test_short_trade_direction_alignment_is_mirrored():
    engine = EnterpriseCorroborationEngine()
    trade = make_trade(Direction.SHORT)
    pos = make_position(direction="SHORT")

    result = engine.corroborate(trade=trade, positions=[pos])

    assert len(result.additional_supporting_data) == 1
    assert result.additional_risks == []


def test_no_positions_is_empty():
    engine = EnterpriseCorroborationEngine()
    trade = make_trade(Direction.LONG)

    result = engine.corroborate(trade=trade, positions=[])

    assert result.is_empty
