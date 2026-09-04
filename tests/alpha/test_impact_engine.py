"""tests/alpha/test_impact_engine.py -- AlphaImpact(TM)'s deterministic causal-chain
builder. Table-driven where useful, mirroring tests/alpha/test_materiality.py's style:
one class of tests per invariant the engine must hold regardless of signal_type."""

from __future__ import annotations

import pytest
from alpha_service.impact_engine import ImpactEngine
from schemas import ImpactCategory, Signal, SignalDirection, SignalType


def make_signal(**overrides) -> Signal:
    defaults = dict(
        signal_type=SignalType.STORAGE_CHANGE,
        category="fundamentals",
        headline="Storage forecast shifted",
        description="Storage forecast is now -90 Bcf (consensus -55 Bcf).",
        materiality_score=88.0,
        confidence=0.8,
        direction=SignalDirection.BEARISH,
        absolute_change=-35.0,
        time_horizon="1W",
    )
    defaults.update(overrides)
    return Signal(**defaults)


@pytest.fixture
def engine() -> ImpactEngine:
    return ImpactEngine()


class TestChainStructure:
    def test_fundamentals_signal_gets_the_full_eight_stage_chain(self, engine):
        analysis = engine.analyze(make_signal(signal_type=SignalType.STORAGE_CHANGE))
        assert len(analysis.chain) == 8
        assert analysis.chain[0].category == ImpactCategory.PHYSICAL
        assert analysis.chain[-1].category == ImpactCategory.RISK

    def test_market_signal_skips_physical_supply_storage_regional_stages(self, engine):
        analysis = engine.analyze(make_signal(signal_type=SignalType.PRICE_MOVE))
        categories = [edge.category for edge in analysis.chain]
        assert categories == [
            ImpactCategory.PRICE_CURVE,
            ImpactCategory.STRATEGY,
            ImpactCategory.PORTFOLIO,
            ImpactCategory.RISK,
        ]

    def test_agent_disagreement_signal_gets_the_shortest_chain(self, engine):
        analysis = engine.analyze(make_signal(signal_type=SignalType.AGENT_DISAGREEMENT))
        categories = [edge.category for edge in analysis.chain]
        assert categories == [ImpactCategory.STRATEGY, ImpactCategory.PORTFOLIO, ImpactCategory.RISK]

    def test_every_chain_ends_in_portfolio_then_risk(self, engine):
        """Every signal type's chain reaches a portfolio question and then a risk
        question last -- already-portfolio-level signal types (POSITION_CHANGE etc.)
        skip the STRATEGY translation stage since they're already about the
        portfolio, so only the final two stages are universal, not three."""
        for signal_type in SignalType:
            analysis = engine.analyze(make_signal(signal_type=signal_type))
            tail = [edge.category for edge in analysis.chain[-2:]]
            assert tail == [ImpactCategory.PORTFOLIO, ImpactCategory.RISK]

    def test_sequence_indices_are_contiguous_from_zero(self, engine):
        analysis = engine.analyze(make_signal())
        assert [edge.sequence_index for edge in analysis.chain] == list(range(len(analysis.chain)))


class TestDecay:
    def test_confidence_never_increases_along_the_chain(self, engine):
        analysis = engine.analyze(make_signal())
        confidences = [edge.confidence for edge in analysis.chain]
        assert confidences == sorted(confidences, reverse=True)
        assert confidences[0] <= analysis.confidence  # first edge is already at or below the signal's own confidence

    def test_magnitude_never_increases_along_the_chain(self, engine):
        analysis = engine.analyze(make_signal())
        magnitudes = [edge.magnitude for edge in analysis.chain]
        assert magnitudes == sorted(magnitudes, reverse=True)


class TestFundamentalImpactMapping:
    def test_storage_change_maps_to_storage_impact_bcf(self, engine):
        analysis = engine.analyze(make_signal(signal_type=SignalType.STORAGE_CHANGE, absolute_change=-35.0))
        assert analysis.storage_impact_bcf == -35.0
        assert analysis.supply_impact_bcf_day is None
        assert analysis.demand_impact_bcf_day is None

    def test_production_change_maps_to_supply_impact(self, engine):
        analysis = engine.analyze(make_signal(signal_type=SignalType.PRODUCTION_CHANGE, absolute_change=1.2))
        assert analysis.supply_impact_bcf_day == 1.2
        assert analysis.storage_impact_bcf is None

    def test_weather_change_maps_to_demand_impact(self, engine):
        analysis = engine.analyze(make_signal(signal_type=SignalType.WEATHER_CHANGE, absolute_change=2.5))
        assert analysis.demand_impact_bcf_day == 2.5

    def test_price_move_has_no_fundamental_bcf_impact(self, engine):
        """A pure market signal shouldn't fabricate a supply/demand/storage number."""
        analysis = engine.analyze(make_signal(signal_type=SignalType.PRICE_MOVE, absolute_change=0.5))
        assert analysis.supply_impact_bcf_day is None
        assert analysis.demand_impact_bcf_day is None
        assert analysis.storage_impact_bcf is None


class TestFieldsCarriedForward:
    def test_bullish_bearish_matches_signal_direction(self, engine):
        analysis = engine.analyze(make_signal(direction=SignalDirection.BULLISH))
        assert analysis.bullish_bearish == SignalDirection.BULLISH

    def test_magnitude_matches_signal_materiality(self, engine):
        analysis = engine.analyze(make_signal(materiality_score=73.0))
        assert analysis.magnitude == 73.0

    def test_signal_id_and_organization_id_are_linked(self, engine):
        sig = make_signal(organization_id="org-1")
        analysis = engine.analyze(sig)
        assert analysis.signal_id == sig.id
        assert analysis.organization_id == "org-1"

    def test_agent_disagreement_gets_an_alternative_interpretation_note(self, engine):
        analysis = engine.analyze(make_signal(signal_type=SignalType.AGENT_DISAGREEMENT))
        assert len(analysis.alternative_interpretations) == 1

    def test_non_disagreement_signal_has_no_alternative_interpretation(self, engine):
        analysis = engine.analyze(make_signal(signal_type=SignalType.STORAGE_CHANGE))
        assert analysis.alternative_interpretations == []

    def test_assumptions_and_uncertainties_are_always_present(self, engine):
        """Every analysis must self-document that per-stage magnitudes are a fixed
        decay heuristic, not an independently modeled quantity -- never silently
        imply more precision than the milestone actually delivers."""
        analysis = engine.analyze(make_signal())
        assert len(analysis.assumptions) >= 1
        assert len(analysis.uncertainties) >= 1
