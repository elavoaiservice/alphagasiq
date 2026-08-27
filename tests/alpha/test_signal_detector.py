"""tests/alpha/test_signal_detector.py -- proves `SignalDetector.detect()` fires on a
genuinely material cycle-over-cycle change and stays silent on a small one, using a
synthetic `ResearchCycleResult`-shaped stand-in rather than running the real agents
(this module is pure and takes only already-computed `AgentResult`s, so no live agent
execution is needed to exercise it)."""

from __future__ import annotations

from dataclasses import dataclass

from alpha_service.materiality import MaterialityEngine
from alpha_service.signal_detector import BaselineSnapshot, SignalDetector
from schemas import AgentResult, AgentStatus, AgentType, DataClassification, SignalType


@dataclass
class _FakeObservation:
    symbol: str
    value: float
    source_type: DataClassification = DataClassification.SIMULATED


@dataclass
class _FakeResearchResult:
    supply: AgentResult | None = None
    demand: AgentResult | None = None
    storage: AgentResult | None = None
    weather: AgentResult | None = None


def make_result(**outputs_by_agent) -> AgentResult:
    return AgentResult(
        agent_id="test.agent",
        agent_name="Test Agent",
        agent_type=AgentType.STORAGE,
        version="0.0.0",
        status=AgentStatus.SUCCESS,
        outputs=outputs_by_agent,
        confidence=0.7,
    )


def make_detector() -> SignalDetector:
    return SignalDetector(MaterialityEngine())


class TestPriceMoveDetection:
    def test_large_price_move_emits_a_signal(self):
        detector = make_detector()
        baselines = {
            "MARKET.price": BaselineSnapshot(
                key="MARKET.price", value=3.0, rolling_window=[2.9, 3.0, 3.05, 2.95, 3.0, 3.02, 2.98]
            )
        }
        market_curve = [_FakeObservation(symbol="NGZ26", value=4.5)]
        signals, updated = detector.detect(
            research_result=_FakeResearchResult(),
            lng_result=None,
            power_result=None,
            pipeline_result=None,
            market_curve=market_curve,
            baselines=baselines,
        )
        assert len(signals) == 1
        assert signals[0].signal_type == SignalType.PRICE_MOVE
        assert signals[0].materiality_score >= 60.0
        assert updated["MARKET.price"].value == 4.5

    def test_tiny_price_move_emits_nothing(self):
        detector = make_detector()
        baselines = {
            "MARKET.price": BaselineSnapshot(
                key="MARKET.price", value=3.0, rolling_window=[2.9, 3.0, 3.05, 2.95, 3.0, 3.02, 2.98]
            )
        }
        market_curve = [_FakeObservation(symbol="NGZ26", value=3.001)]
        signals, _ = detector.detect(
            research_result=_FakeResearchResult(),
            lng_result=None,
            power_result=None,
            pipeline_result=None,
            market_curve=market_curve,
            baselines=baselines,
        )
        assert signals == []

    def test_first_observation_of_a_metric_seeds_baseline_without_a_signal(self):
        """Nothing to diff against yet -- the very first cycle a metric is seen must
        never fire a signal, however large the absolute value looks."""
        detector = make_detector()
        market_curve = [_FakeObservation(symbol="NGZ26", value=9999.0)]
        signals, updated = detector.detect(
            research_result=_FakeResearchResult(),
            lng_result=None,
            power_result=None,
            pipeline_result=None,
            market_curve=market_curve,
            baselines={},
        )
        assert signals == []
        assert updated["MARKET.price"].value == 9999.0


class TestStorageChangeDetection:
    def test_large_storage_forecast_shift_emits_a_signal(self):
        detector = make_detector()
        baselines = {"STORAGE.forecast_bcf": BaselineSnapshot(key="STORAGE.forecast_bcf", value=50.0, rolling_window=[48, 50, 52, 49, 51])}
        result = _FakeResearchResult(storage=make_result(forecast_bcf=90.0, market_consensus_bcf=55.0))
        signals, _ = detector.detect(
            research_result=result,
            lng_result=None,
            power_result=None,
            pipeline_result=None,
            market_curve=[],
            baselines=baselines,
        )
        storage_signals = [s for s in signals if s.signal_type == SignalType.STORAGE_CHANGE]
        assert len(storage_signals) == 1
        # A bigger-than-expected injection is bearish.
        assert storage_signals[0].direction.value == "BEARISH"

    def test_skipped_storage_agent_produces_no_signal(self):
        """A SKIPPED agent's outputs are empty -- must not crash and must not fire."""
        detector = make_detector()
        skipped = AgentResult(
            agent_id="test.agent",
            agent_name="Storage Agent",
            agent_type=AgentType.STORAGE,
            version="0.0.0",
            status=AgentStatus.SKIPPED,
        )
        result = _FakeResearchResult(storage=skipped)
        signals, _ = detector.detect(
            research_result=result,
            lng_result=None,
            power_result=None,
            pipeline_result=None,
            market_curve=[],
            baselines={"STORAGE.forecast_bcf": BaselineSnapshot(key="STORAGE.forecast_bcf", value=50.0, rolling_window=[50])},
        )
        assert signals == []


class TestAgentDisagreement:
    def test_fewer_than_three_directional_reads_never_fires(self):
        detector = make_detector()
        result = _FakeResearchResult(
            storage=make_result(forecast_bcf=90.0, market_consensus_bcf=55.0),
            weather=make_result(price_direction="BEARISH"),
        )
        signals, _ = detector.detect(
            research_result=result,
            lng_result=None,
            power_result=None,
            pipeline_result=None,
            market_curve=[],
            baselines={},
        )
        assert not any(s.signal_type == SignalType.AGENT_DISAGREEMENT for s in signals)

    def test_split_directional_reads_can_fire_agent_disagreement(self):
        detector = make_detector()
        result = _FakeResearchResult(
            storage=make_result(forecast_bcf=90.0, market_consensus_bcf=55.0),  # BEARISH (looser than consensus)
            weather=make_result(price_direction="BULLISH"),
            supply=make_result(production_trend_bcf_d=-2.0),  # BULLISH (falling production)
            demand=make_result(demand_trend_bcf_d=-2.0),  # BEARISH (falling demand)
        )
        signals, _ = detector.detect(
            research_result=result,
            lng_result=None,
            power_result=None,
            pipeline_result=None,
            market_curve=[],
            baselines={},
        )
        disagreement = [s for s in signals if s.signal_type == SignalType.AGENT_DISAGREEMENT]
        assert len(disagreement) == 1
        assert "2 bullish" in disagreement[0].description or "2 bearish" in disagreement[0].description

    def test_unanimous_directional_reads_never_fire_disagreement(self):
        detector = make_detector()
        result = _FakeResearchResult(
            storage=make_result(forecast_bcf=40.0, market_consensus_bcf=55.0),  # BULLISH (tighter)
            weather=make_result(price_direction="BULLISH"),
            supply=make_result(production_trend_bcf_d=-2.0),  # BULLISH
            demand=make_result(demand_trend_bcf_d=2.0),  # BULLISH
        )
        signals, _ = detector.detect(
            research_result=result,
            lng_result=None,
            power_result=None,
            pipeline_result=None,
            market_curve=[],
            baselines={},
        )
        assert not any(s.signal_type == SignalType.AGENT_DISAGREEMENT for s in signals)


class TestOptionalAgentResults:
    def test_none_lng_power_pipeline_results_are_skipped_without_error(self):
        """`run_chief_trading_cycle` doesn't re-run LNG/power/pipeline -- detect() must
        tolerate all three being None."""
        detector = make_detector()
        signals, updated = detector.detect(
            research_result=_FakeResearchResult(),
            lng_result=None,
            power_result=None,
            pipeline_result=None,
            market_curve=[],
            baselines={},
        )
        assert signals == []
        assert updated == {}
