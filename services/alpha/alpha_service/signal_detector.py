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
AGENT_DISAGREEMENT check across the fundamental agents' directional leans. A later pass
added PORTFOLIO_CHANGE (live paper-portfolio exposure, cycle-over-cycle) and
RISK_LIMIT_APPROACH (how close `AppState.current_daily_loss`/`current_drawdown` are to
their configured `RiskLimits`).

Honestly still not produced, and why: NEWS_EVENT and CUSTOMER_DATA_CHANGE need a source
that actually refreshes cycle-over-cycle (`AppState.news_events` is set once at boot,
never re-fetched; enterprise records have no polling loop either -- both are natural
follow-ups once NEWS_INTELLIGENCE is wired into orchestration and per-organization
enterprise detection exists, respectively, not something to fake here). POSITION_CHANGE
is the same per-organization-loop problem. REGULATORY_EVENT has no data source anywhere
in this codebase (no regulatory-filing connector exists). MODEL_DISAGREEMENT would
require running multiple Quantitative Team models per cycle instead of the one
`ForecastingAgent` runs today -- restructuring that pipeline was judged too invasive for
this pass, the same caution `_detect_agent_disagreement`'s own docstring already applies
to calling itself "AGENT_DISAGREEMENT" rather than a true model-disagreement check.
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

# Provisional judgment call (same discipline as MaterialityEngine's own weights): a hard
# risk limit is "being approached" once this fraction of it is used. RISK_LIMIT_APPROACH
# deliberately does not route through MaterialityEngine.score() -- its magnitude/rarity
# components are calibrated for market percent-changes and z-scores, not "fraction of a
# fixed regulatory-style limit consumed," so reusing them here would saturate materiality
# at an arbitrarily low usage fraction. materiality_score is instead simply the usage
# fraction itself, scaled to 0-100 and capped there.
_RISK_LIMIT_APPROACH_THRESHOLD_FRACTION = 0.7


@dataclass
class BaselineSnapshot:
    """The last-known value for one detector key (e.g. `"STORAGE.forecast_bcf"`), plus
    a bounded rolling window used to compute a z-score for rarity scoring, and a bounded
    history of whether each recent cycle actually produced a materiality-passing signal
    for this key -- used to compute `Signal.novelty_score` (see `_novelty_score`)."""

    key: str
    value: float
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    rolling_window: list[float] = field(default_factory=list)
    signal_emitted_history: list[bool] = field(default_factory=list)


def _novelty_score(history: list[bool]) -> float:
    """Recurrence-based novelty (docs/alpha-intelligence.md's Milestone 1 provisional
    decision #5, implemented as real follow-up work): how often this detector key has
    *actually produced a materiality-passing signal* over its recent history, inverted
    -- a key that fires every cycle is never surprising (novelty near 0); a key with no
    recorded history at all, or one that has never fired before, is maximally novel
    (100) rather than defaulting to 0, since "never seen before" is the most novel case
    there is, not the least."""
    if not history:
        return 100.0
    recurrence_fraction = sum(1 for fired in history if fired) / len(history)
    return round(100.0 * (1.0 - recurrence_fraction), 2)


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
        portfolio_exposure: float | None = None,
        risk_limit_usage: dict[str, float] | None = None,
    ) -> tuple[list[Signal], dict[str, BaselineSnapshot]]:
        """`portfolio_exposure`/`risk_limit_usage` are optional so every existing caller
        (and every existing test) that doesn't pass them keeps working unchanged.
        `risk_limit_usage` maps a limit name (e.g. `"DAILY_LOSS"`, `"DRAWDOWN"`) to its
        current usage as a fraction of the configured `RiskLimits` value (already
        computed by the caller -- this module has no `RiskLimits` of its own)."""
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
            novelty = _novelty_score(baseline.signal_emitted_history)
            new_history = (baseline.signal_emitted_history + [score_result.passed_threshold])[
                -_ROLLING_WINDOW_SIZE:
            ]
            updated[key] = BaselineSnapshot(
                key=key, value=current_value, rolling_window=new_window, signal_emitted_history=new_history
            )

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
                    novelty_score=novelty,
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

        if portfolio_exposure is not None:
            _consider(
                key="PORTFOLIO.total_exposure",
                current_value=portfolio_exposure,
                signal_type=SignalType.PORTFOLIO_CHANGE,
                category="portfolio",
                headline="Portfolio exposure changed",
                description=f"Total paper-portfolio exposure is now {portfolio_exposure:,.0f}.",
                confidence=1.0,  # deterministic from live paper-portfolio state, not a model estimate
                data_quality=DataClassification.SIMULATED,
                source_ids=["PAPER_EXECUTION"],
            )

        signals.extend(
            self._detect_agent_disagreement(
                storage=storage, weather=weather, supply=supply, demand=demand, market=market, baselines=updated
            )
        )
        signals.extend(
            self._detect_risk_limit_approach(risk_limit_usage=risk_limit_usage, baselines=updated, market=market)
        )

        return signals, updated

    def _detect_risk_limit_approach(
        self,
        *,
        risk_limit_usage: dict[str, float] | None,
        baselines: dict[str, BaselineSnapshot],
        market: str,
    ) -> list[Signal]:
        """See the module docstring and `_RISK_LIMIT_APPROACH_THRESHOLD_FRACTION` for why
        this deliberately does not route through `MaterialityEngine.score()`. Mutates
        `baselines` in place (same pattern as `_detect_agent_disagreement`) so novelty can
        accumulate across cycles for each limit independently."""
        if not risk_limit_usage:
            return []
        signals: list[Signal] = []
        for limit_name, fraction in risk_limit_usage.items():
            key = f"RISK.{limit_name}"
            baseline = baselines.get(key)
            history = baseline.signal_emitted_history if baseline is not None else []
            fired = fraction >= _RISK_LIMIT_APPROACH_THRESHOLD_FRACTION
            novelty = _novelty_score(history)
            new_history = (history + [fired])[-_ROLLING_WINDOW_SIZE:]
            baselines[key] = BaselineSnapshot(key=key, value=fraction, signal_emitted_history=new_history)
            if not fired:
                continue
            materiality = round(min(100.0, max(0.0, fraction * 100.0)), 2)
            signals.append(
                Signal(
                    signal_type=SignalType.RISK_LIMIT_APPROACH,
                    category="risk",
                    market=market,
                    headline=f"{limit_name.replace('_', ' ').title()} approaching its configured limit",
                    description=(
                        f"{limit_name.replace('_', ' ').title()} usage is at {fraction:.0%} of its "
                        "configured RiskLimits value."
                    ),
                    current_value=fraction,
                    materiality_score=materiality,
                    novelty_score=novelty,
                    confidence=1.0,  # deterministic from RiskLimits/AppState, not a model estimate
                    direction=SignalDirection.NEUTRAL,  # a risk-usage caution, not a market direction read
                    data_quality=DataClassification.SIMULATED,
                    affected_agents=["RISK_GOVERNOR"],
                )
            )
        return signals

    def _detect_agent_disagreement(
        self, *, storage, weather, supply, demand, market: str, baselines: dict[str, BaselineSnapshot]
    ) -> list[Signal]:
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

        key = "AGENT_DISAGREEMENT"
        baseline = baselines.get(key)
        history = baseline.signal_emitted_history if baseline is not None else []
        novelty = _novelty_score(history)
        new_history = (history + [score_result.passed_threshold])[-_ROLLING_WINDOW_SIZE:]
        baselines[key] = BaselineSnapshot(key=key, value=disagreement_fraction, signal_emitted_history=new_history)

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
                novelty_score=novelty,
                confidence=avg_confidence,
                direction=SignalDirection.NEUTRAL,
                data_quality=DataClassification.SIMULATED,
                affected_agents=["SUPPLY", "DEMAND", "STORAGE", "WEATHER"],
            )
        ]
