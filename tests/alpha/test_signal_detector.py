"""tests/alpha/test_signal_detector.py -- proves `SignalDetector.detect()` fires on a
genuinely material cycle-over-cycle change and stays silent on a small one, using a
synthetic `ResearchCycleResult`-shaped stand-in rather than running the real agents
(this module is pure and takes only already-computed `AgentResult`s, so no live agent
execution is needed to exercise it)."""

from __future__ import annotations

from dataclasses import dataclass

from alpha_service.materiality import MaterialityEngine
from alpha_service.signal_detector import BaselineSnapshot, SignalDetector, _novelty_score
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


class TestNoveltyScorePureFunction:
    def test_empty_history_is_maximally_novel(self):
        assert _novelty_score([]) == 100.0

    def test_always_fired_history_is_never_novel(self):
        assert _novelty_score([True, True, True, True]) == 0.0

    def test_never_fired_history_stays_maximally_novel(self):
        assert _novelty_score([False, False, False]) == 100.0

    def test_mixed_history_is_between_the_extremes(self):
        score = _novelty_score([True, False, True, False])
        assert 0.0 < score < 100.0
        assert score == 50.0


class TestNoveltyScoreInDetection:
    def test_first_ever_material_price_move_is_maximally_novel(self):
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
        assert signals[0].novelty_score == 100.0
        assert updated["MARKET.price"].signal_emitted_history == [True]

    def test_a_signal_that_recurs_every_cycle_becomes_less_novel_over_time(self):
        """Feeding the detector's own `updated` baselines back in on each call (as
        `AppState` does across research cycles) lets novelty genuinely decay as a
        metric keeps moving materially cycle after cycle."""
        detector = make_detector()
        baselines = {
            "MARKET.price": BaselineSnapshot(
                key="MARKET.price", value=3.0, rolling_window=[2.9, 3.0, 3.05, 2.95, 3.0, 3.02, 2.98]
            )
        }
        novelty_scores = []
        price = 4.5
        for _ in range(5):
            signals, baselines = detector.detect(
                research_result=_FakeResearchResult(),
                lng_result=None,
                power_result=None,
                pipeline_result=None,
                market_curve=[_FakeObservation(symbol="NGZ26", value=price)],
                baselines=baselines,
            )
            novelty_scores.append(signals[0].novelty_score)
            price += 1.5  # keep the move large enough to clear materiality each cycle

        assert novelty_scores[0] == 100.0
        assert novelty_scores[-1] < novelty_scores[0]

    def test_agent_disagreement_signal_carries_a_novelty_score(self):
        detector = make_detector()
        result = _FakeResearchResult(
            storage=make_result(forecast_bcf=90.0, market_consensus_bcf=55.0),
            weather=make_result(price_direction="BULLISH"),
            supply=make_result(production_trend_bcf_d=-2.0),
            demand=make_result(demand_trend_bcf_d=-2.0),
        )
        signals, updated = detector.detect(
            research_result=result,
            lng_result=None,
            power_result=None,
            pipeline_result=None,
            market_curve=[],
            baselines={},
        )
        disagreement = [s for s in signals if s.signal_type == SignalType.AGENT_DISAGREEMENT]
        assert len(disagreement) == 1
        assert disagreement[0].novelty_score == 100.0
        assert updated["AGENT_DISAGREEMENT"].signal_emitted_history == [True]


class TestPortfolioChangeDetection:
    def test_large_exposure_change_emits_a_signal(self):
        detector = make_detector()
        baselines = {
            "PORTFOLIO.total_exposure": BaselineSnapshot(
                key="PORTFOLIO.total_exposure", value=10_000.0, rolling_window=[9_800, 10_000, 10_200, 9_900, 10_100]
            )
        }
        signals, updated = detector.detect(
            research_result=_FakeResearchResult(),
            lng_result=None,
            power_result=None,
            pipeline_result=None,
            market_curve=[],
            baselines=baselines,
            portfolio_exposure=50_000.0,
        )
        portfolio_signals = [s for s in signals if s.signal_type == SignalType.PORTFOLIO_CHANGE]
        assert len(portfolio_signals) == 1
        assert updated["PORTFOLIO.total_exposure"].value == 50_000.0

    def test_no_exposure_argument_emits_nothing(self):
        detector = make_detector()
        signals, updated = detector.detect(
            research_result=_FakeResearchResult(),
            lng_result=None,
            power_result=None,
            pipeline_result=None,
            market_curve=[],
            baselines={},
        )
        assert not any(s.signal_type == SignalType.PORTFOLIO_CHANGE for s in signals)
        assert "PORTFOLIO.total_exposure" not in updated


class TestRiskLimitApproachDetection:
    def test_usage_below_threshold_never_fires(self):
        detector = make_detector()
        signals, updated = detector.detect(
            research_result=_FakeResearchResult(),
            lng_result=None,
            power_result=None,
            pipeline_result=None,
            market_curve=[],
            baselines={},
            risk_limit_usage={"DAILY_LOSS": 0.3},
        )
        assert not any(s.signal_type == SignalType.RISK_LIMIT_APPROACH for s in signals)
        # Still tracked for novelty purposes even when it doesn't fire.
        assert updated["RISK.DAILY_LOSS"].signal_emitted_history == [False]

    def test_usage_at_or_above_threshold_fires_with_scaled_materiality(self):
        detector = make_detector()
        signals, updated = detector.detect(
            research_result=_FakeResearchResult(),
            lng_result=None,
            power_result=None,
            pipeline_result=None,
            market_curve=[],
            baselines={},
            risk_limit_usage={"DRAWDOWN": 0.85},
        )
        drawdown_signals = [s for s in signals if s.signal_type == SignalType.RISK_LIMIT_APPROACH]
        assert len(drawdown_signals) == 1
        assert drawdown_signals[0].materiality_score == 85.0
        assert drawdown_signals[0].novelty_score == 100.0
        assert drawdown_signals[0].direction == "NEUTRAL"
        assert updated["RISK.DRAWDOWN"].signal_emitted_history == [True]

    def test_no_risk_limit_usage_argument_emits_nothing(self):
        detector = make_detector()
        signals, updated = detector.detect(
            research_result=_FakeResearchResult(),
            lng_result=None,
            power_result=None,
            pipeline_result=None,
            market_curve=[],
            baselines={},
        )
        assert not any(s.signal_type == SignalType.RISK_LIMIT_APPROACH for s in signals)
        assert updated == {}

    def test_multiple_limits_tracked_independently(self):
        detector = make_detector()
        signals, updated = detector.detect(
            research_result=_FakeResearchResult(),
            lng_result=None,
            power_result=None,
            pipeline_result=None,
            market_curve=[],
            baselines={},
            risk_limit_usage={"DAILY_LOSS": 0.9, "DRAWDOWN": 0.1},
        )
        fired_types = {s.signal_type for s in signals}
        assert SignalType.RISK_LIMIT_APPROACH in fired_types
        assert len([s for s in signals if s.signal_type == SignalType.RISK_LIMIT_APPROACH]) == 1
        assert "RISK.DAILY_LOSS" in updated
        assert "RISK.DRAWDOWN" in updated


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
