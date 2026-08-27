"""AlphaSignal(TM)'s cycle-over-cycle change detector (docs/alpha-intelligence.md
section 2).

`SignalDetector.detect()` is a pure function: it takes the current research cycle's
already-computed fundamental-agent outputs plus the previous cycle's stored baselines,
and returns any `Signal`s that cleared the `MaterialityEngine`'s threshold, plus the
updated baselines. No DB or event-bus access happens here -- the caller (`AppState`)
persists the returned baselines/signals and publishes events, exactly the same
separation of concerns `risk_service.governor.RiskGovernor` uses (pure evaluation,
caller owns all I/O).

Milestone 1 detects: PRICE_MOVE, STORAGE_CHANGE, WEATHER_CHANGE, PRODUCTION_CHANGE,
DEMAND_CHANGE, LNG_CHANGE, POWER_CHANGE, PIPELINE_CONSTRAINT, and a simple
AGENT_DISAGREEMENT check across the fundamental agents' directional leans. Every other
`SignalType` value exists on the schema for forward-compatibility but is not yet
produced by this detector (see docs/alpha-intelligence.md's Milestone 1 scope notes).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import fmean, pstdev
from typing import Any, Callable

from schemas import AgentResult, Citation, DataClassification, Signal, SignalDirection, SignalType

from .materiality import MaterialityEngine, MaterialityInput

_ROLLING_WINDOW_SIZE = 20
_MIN_SAMPLES_FOR_ZSCORE = 3
_MIN_AGENTS_FOR_DISAGREEMENT_CHECK = 3


@dataclass
class BaselineSnapshot:
    """The last-known value for one detector key (e.g. `"STORAGE.forecast_bcf"`), plus
    a bounded rolling window used to compute a z-score for rarity scoring."""

    key: str
    value: float
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    rolling_window: list[float] = field(default_factory=list)


def _zscore(window: list[float], current: float) -> float | None:
    if len(window) < _MIN_SAMPLES_FOR_ZSCORE:
        return None
    mean = fmean(window)
    stdev = pstdev(window)
    if stdev == 0:
        return None
    return (current - mean) / stdev


class SignalDetector:
    def __init__(self, engine: MaterialityEngine):
        self._engine = engine

    def detect(
        self,
        *,
        research_result: Any,  # agents_service.ResearchCycleResult -- not imported to
        # avoid a services/alpha -> services/agents package dependency for a type hint.
        lng_result: AgentResult | None,
        power_result: AgentResult | None,
        pipeline_result: AgentResult | None,
        market_curve: list,  # list[ObservationDraft]-like: needs .symbol/.value/.source_type
        baselines: dict[str, BaselineSnapshot],
    ) -> tuple[list[Signal], dict[str, BaselineSnapshot]]:
        signals: list[Signal] = []
        updated: dict[str, BaselineSnapshot] = dict(baselines)
        market = market_curve[0].symbol if market_curve else "HENRY_HUB"

        def _consider(
            *,
            key: str,
            current_value: float | None,
            signal_type: SignalType,
            category: str,
            headline: str,
            description: str,
            confidence: float,
            data_quality: DataClassification,
            direction_fn: Callable[[float], SignalDirection] | None = None,
            source_ids: list[str] | None = None,
            citations: list[Citation] | None = None,
        ) -> None:
            if current_value is None:
                return
            baseline = updated.get(key)
            if baseline is None:
                updated[key] = BaselineSnapshot(key=key, value=current_value, rolling_window=[current_value])
                return  # first observation of this metric -- nothing to diff against yet

            absolute_change = current_value - baseline.value
            percent_change = absolute_change / baseline.value if baseline.value else None
            z = _zscore(baseline.rolling_window, current_value)

            score_result = self._engine.score(
                MaterialityInput(
                    signal_type=signal_type,
                    absolute_change=absolute_change,
                    percent_change=percent_change,
                    z_score=z,
                    confidence=confidence,
                    data_quality=data_quality,
                )
            )

            new_window = (baseline.rolling_window + [current_value])[-_ROLLING_WINDOW_SIZE:]
            updated[key] = BaselineSnapshot(key=key, value=current_value, rolling_window=new_window)

            if not score_result.passed_threshold:
                return

            signals.append(
                Signal(
                    signal_type=signal_type,
                    category=category,
                    source_ids=source_ids or [],
                    market=market,
                    headline=headline,
                    description=description,
                    previous_value=baseline.value,
                    current_value=current_value,
                    absolute_change=absolute_change,
                    percent_change=percent_change,
                    z_score=z,
                    materiality_score=score_result.score,
                    confidence=confidence,
                    direction=direction_fn(absolute_change) if direction_fn else SignalDirection.NEUTRAL,
                    data_quality=data_quality,
                    citations=citations or [],
                    affected_agents=source_ids or [],
                )
            )

        if market_curve:
            front = market_curve[0]
            _consider(
                key="MARKET.price",
                current_value=front.value,
                signal_type=SignalType.PRICE_MOVE,
                category="market",
                headline=f"{front.symbol} front-month price moved",
                description=f"{front.symbol} front-month is now {front.value:.3f}.",
                confidence=0.9,
                data_quality=front.source_type,
                direction_fn=lambda d: SignalDirection.BULLISH if d > 0 else SignalDirection.BEARISH,
                source_ids=["MARKET_DATA"],
            )

        storage = research_result.storage
        if storage is not None and storage.outputs:
            outputs = storage.outputs
            _consider(
                key="STORAGE.forecast_bcf",
                current_value=outputs.get("forecast_bcf"),
                signal_type=SignalType.STORAGE_CHANGE,
                category="fundamentals",
                headline="Storage forecast shifted",
                description=(
                    f"Storage forecast is now {outputs.get('forecast_bcf', 0):+.0f} Bcf "
                    f"(consensus {outputs.get('market_consensus_bcf')} Bcf)."
                ),
                confidence=storage.confidence or 0.5,
                data_quality=DataClassification.SIMULATED,
                # A bigger injection (positive forecast_bcf) than before is bearish;
                # a bigger withdrawal (more negative) is bullish.
                direction_fn=lambda d: SignalDirection.BEARISH if d > 0 else SignalDirection.BULLISH,
                source_ids=["STORAGE"],
                citations=storage.citations,
            )

        weather = research_result.weather
        if weather is not None and weather.outputs:
            outputs = weather.outputs
            _consider(
                key="WEATHER.total_demand_delta_bcf",
                current_value=outputs.get("total_demand_delta_bcf"),
                signal_type=SignalType.WEATHER_CHANGE,
                category="fundamentals",
                headline="Weather-driven demand outlook changed",
                description=(
                    f"Total demand delta now {outputs.get('total_demand_delta_bcf', 0):+.2f} Bcf/d "
                    f"({outputs.get('price_direction')})."
                ),
                confidence=weather.confidence or 0.5,
                data_quality=DataClassification.SIMULATED,
                direction_fn=lambda d: SignalDirection.BULLISH if d > 0 else SignalDirection.BEARISH,
                source_ids=["WEATHER"],
                citations=weather.citations,
            )

        supply = research_result.supply
        if supply is not None and supply.outputs:
            outputs = supply.outputs
            _consider(
                key="SUPPLY.production_trend_bcf_d",
                current_value=outputs.get("production_trend_bcf_d"),
                signal_type=SignalType.PRODUCTION_CHANGE,
                category="fundamentals",
                headline="Production trend changed",
                description=f"Production trend is now {outputs.get('production_trend_bcf_d', 0):+.2f} Bcf/d.",
                confidence=supply.confidence or 0.5,
                data_quality=DataClassification.SIMULATED,
                direction_fn=lambda d: SignalDirection.BEARISH if d > 0 else SignalDirection.BULLISH,
                source_ids=["SUPPLY"],
                citations=supply.citations,
            )

        demand = research_result.demand
        if demand is not None and demand.outputs:
            outputs = demand.outputs
            _consider(
                key="DEMAND.demand_trend_bcf_d",
                current_value=outputs.get("demand_trend_bcf_d"),
                signal_type=SignalType.DEMAND_CHANGE,
                category="fundamentals",
                headline="Demand trend changed",
                description=f"Demand trend is now {outputs.get('demand_trend_bcf_d', 0):+.2f} Bcf/d.",
                confidence=demand.confidence or 0.5,
                data_quality=DataClassification.SIMULATED,
                direction_fn=lambda d: SignalDirection.BULLISH if d > 0 else SignalDirection.BEARISH,
                source_ids=["DEMAND"],
                citations=demand.citations,
            )

        if lng_result is not None and lng_result.outputs:
            outputs = lng_result.outputs
            _consider(
                key="LNG.total_feedgas_bcf_d",
                current_value=outputs.get("total_feedgas_bcf_d"),
                signal_type=SignalType.LNG_CHANGE,
                category="fundamentals",
                headline="LNG feedgas demand changed",
                description=f"Total LNG feedgas now {outputs.get('total_feedgas_bcf_d', 0):.2f} Bcf/d.",
                confidence=lng_result.confidence or 0.5,
                data_quality=DataClassification.SIMULATED,
                direction_fn=lambda d: SignalDirection.BULLISH if d > 0 else SignalDirection.BEARISH,
                source_ids=["LNG"],
                citations=lng_result.citations,
            )

        if power_result is not None and power_result.outputs:
            outputs = power_result.outputs
            _consider(
                key="POWER_MARKET.total_power_burn_bcf_d",
                current_value=outputs.get("total_power_burn_bcf_d"),
                signal_type=SignalType.POWER_CHANGE,
                category="fundamentals",
                headline="Gas-fired power burn changed",
                description=f"Total power burn now {outputs.get('total_power_burn_bcf_d', 0):.2f} Bcf/d.",
                confidence=power_result.confidence or 0.5,
                data_quality=DataClassification.SIMULATED,
                direction_fn=lambda d: SignalDirection.BULLISH if d > 0 else SignalDirection.BEARISH,
                source_ids=["POWER_MARKET"],
                citations=power_result.citations,
            )

        if pipeline_result is not None and pipeline_result.outputs:
            outputs = pipeline_result.outputs
            _consider(
                key="PIPELINE.constrained_corridor_count",
                current_value=outputs.get("constrained_corridor_count"),
                signal_type=SignalType.PIPELINE_CONSTRAINT,
                category="fundamentals",
                headline="Pipeline constraint count changed",
                description=(
                    f"{outputs.get('constrained_corridor_count')} corridor(s) now constrained "
                    f"(avg utilization {outputs.get('average_utilization')})."
                ),
                confidence=pipeline_result.confidence or 0.5,
                data_quality=DataClassification.SIMULATED,
                direction_fn=lambda d: SignalDirection.BULLISH if d > 0 else SignalDirection.BEARISH,
                source_ids=["PIPELINE"],
                citations=pipeline_result.citations,
            )

        signals.extend(self._detect_agent_disagreement(storage=storage, weather=weather, supply=supply, demand=demand, market=market))

        return signals, updated

    def _detect_agent_disagreement(self, *, storage, weather, supply, demand, market: str) -> list[Signal]:
        """A deterministic, simplified directional-agreement check across the
        fundamental agents that expressed a clear lean this cycle. This is
        intentionally not a true multi-model consensus/weighting engine -- that is
        AlphaConsensus (docs/alpha-intelligence.md Milestone 3), not AlphaSignal."""
        directions: list[SignalDirection] = []
        confidences: list[float] = []

        if storage is not None and storage.outputs.get("forecast_bcf") is not None and storage.outputs.get("market_consensus_bcf") is not None:
            directions.append(
                SignalDirection.BULLISH
                if storage.outputs["forecast_bcf"] < storage.outputs["market_consensus_bcf"]
                else SignalDirection.BEARISH
            )
            confidences.append(storage.confidence or 0.5)
        if weather is not None and weather.outputs.get("price_direction") in ("BULLISH", "BEARISH"):
            directions.append(SignalDirection(weather.outputs["price_direction"]))
            confidences.append(weather.confidence or 0.5)
        if supply is not None and supply.outputs.get("production_trend_bcf_d") is not None:
            directions.append(
                SignalDirection.BEARISH if supply.outputs["production_trend_bcf_d"] > 0 else SignalDirection.BULLISH
            )
            confidences.append(supply.confidence or 0.5)
        if demand is not None and demand.outputs.get("demand_trend_bcf_d") is not None:
            directions.append(
                SignalDirection.BULLISH if demand.outputs["demand_trend_bcf_d"] > 0 else SignalDirection.BEARISH
            )
            confidences.append(demand.confidence or 0.5)

        if len(directions) < _MIN_AGENTS_FOR_DISAGREEMENT_CHECK:
            return []

        bullish = directions.count(SignalDirection.BULLISH)
        bearish = directions.count(SignalDirection.BEARISH)
        total = bullish + bearish
        if total == 0:
            return []
        disagreement_fraction = min(bullish, bearish) / total
        if disagreement_fraction <= 0:
            return []

        avg_confidence = fmean(confidences)
        score_result = self._engine.score(
            MaterialityInput(
                signal_type=SignalType.AGENT_DISAGREEMENT,
                percent_change=disagreement_fraction,
                confidence=avg_confidence,
                data_quality=DataClassification.SIMULATED,
            )
        )
        if not score_result.passed_threshold:
            return []

        return [
            Signal(
                signal_type=SignalType.AGENT_DISAGREEMENT,
                category="agent_intelligence",
                market=market,
                headline="Fundamental agents disagree on direction",
                description=(
                    f"{bullish} bullish vs. {bearish} bearish across {total} directional "
                    "fundamental reads this cycle."
                ),
                percent_change=disagreement_fraction,
                materiality_score=score_result.score,
                confidence=avg_confidence,
                direction=SignalDirection.NEUTRAL,
                data_quality=DataClassification.SIMULATED,
                affected_agents=["SUPPLY", "DEMAND", "STORAGE", "WEATHER"],
            )
        ]
