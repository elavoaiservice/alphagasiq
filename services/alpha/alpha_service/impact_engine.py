"""AlphaImpact(TM) (docs/alpha-intelligence.md section 5): takes a `Signal` AlphaSignal
already detected and determines what it *means* -- a causal chain from physical event
to portfolio/risk implication:

    EVENT -> PHYSICAL -> SUPPLY/DEMAND -> STORAGE -> REGIONAL -> PRICE/CURVE ->
    STRATEGY -> PORTFOLIO -> RISK

`ImpactEngine.analyze()` is a pure function of its input, exactly like
`MaterialityEngine.score()` and `SignalDetector.detect()` -- no DB/event-bus/LLM access
happens here. Milestone 2 is deliberately honest about scope: each chain stage's
confidence/magnitude decays from the triggering signal's own confidence/materiality via
a fixed factor rather than an independently-modeled per-stage quantity, and the
`assumptions`/`uncertainties` fields on every `ImpactAnalysis` say so explicitly. A
genuinely independent per-stage model (e.g. translating a production change into a
specific price/curve magnitude) is future work, not fabricated now.
"""

from __future__ import annotations

from schemas import ImpactAnalysis, ImpactCategory, ImpactEdge, Signal, SignalDirection, SignalType

IMPACT_ENGINE_VERSION = "1.0.0"

# Confidence/magnitude multiply by this factor at every subsequent chain stage --
# uncertainty can only compound moving further from the triggering signal, never shrink.
_STAGE_DECAY_FACTOR = 0.92

# Which causal-chain stages actually apply to a given signal type. Every skeleton ends
# in STRATEGY -> PORTFOLIO -> RISK (every signal eventually reaches a
# strategy/portfolio/risk question); earlier stages are included only when they make
# sense for that signal type.
_FUNDAMENTALS_SKELETON = [
    ImpactCategory.PHYSICAL,
    ImpactCategory.SUPPLY_DEMAND,
    ImpactCategory.STORAGE,
    ImpactCategory.REGIONAL,
    ImpactCategory.PRICE_CURVE,
    ImpactCategory.STRATEGY,
    ImpactCategory.PORTFOLIO,
    ImpactCategory.RISK,
]
_MARKET_SKELETON = [
    ImpactCategory.PRICE_CURVE,
    ImpactCategory.STRATEGY,
    ImpactCategory.PORTFOLIO,
    ImpactCategory.RISK,
]
_EVENT_SKELETON = [
    ImpactCategory.PHYSICAL,
    ImpactCategory.PRICE_CURVE,
    ImpactCategory.STRATEGY,
    ImpactCategory.PORTFOLIO,
    ImpactCategory.RISK,
]
_AGENT_INTELLIGENCE_SKELETON = [ImpactCategory.STRATEGY, ImpactCategory.PORTFOLIO, ImpactCategory.RISK]
_PORTFOLIO_SKELETON = [ImpactCategory.PORTFOLIO, ImpactCategory.RISK]

_SKELETON_BY_SIGNAL_TYPE: dict[SignalType, list[ImpactCategory]] = {
    SignalType.PRODUCTION_CHANGE: _FUNDAMENTALS_SKELETON,
    SignalType.DEMAND_CHANGE: _FUNDAMENTALS_SKELETON,
    SignalType.STORAGE_CHANGE: _FUNDAMENTALS_SKELETON,
    SignalType.WEATHER_CHANGE: _FUNDAMENTALS_SKELETON,
    SignalType.LNG_CHANGE: _FUNDAMENTALS_SKELETON,
    SignalType.POWER_CHANGE: _FUNDAMENTALS_SKELETON,
    SignalType.PIPELINE_CONSTRAINT: _FUNDAMENTALS_SKELETON,
    SignalType.PIPELINE_OUTAGE: _FUNDAMENTALS_SKELETON,
    SignalType.PRICE_MOVE: _MARKET_SKELETON,
    SignalType.CURVE_CHANGE: _MARKET_SKELETON,
    SignalType.VOLATILITY_CHANGE: _MARKET_SKELETON,
    SignalType.NEWS_EVENT: _EVENT_SKELETON,
    SignalType.REGULATORY_EVENT: _EVENT_SKELETON,
    SignalType.ANOMALY: _EVENT_SKELETON,
    SignalType.AGENT_DISAGREEMENT: _AGENT_INTELLIGENCE_SKELETON,
    SignalType.MODEL_DISAGREEMENT: _AGENT_INTELLIGENCE_SKELETON,
    SignalType.POSITION_CHANGE: _PORTFOLIO_SKELETON,
    SignalType.PORTFOLIO_CHANGE: _PORTFOLIO_SKELETON,
    SignalType.RISK_LIMIT_APPROACH: _PORTFOLIO_SKELETON,
    SignalType.CUSTOMER_DATA_CHANGE: _PORTFOLIO_SKELETON,
}

_SUPPLY_TYPES = {SignalType.PRODUCTION_CHANGE, SignalType.PIPELINE_CONSTRAINT, SignalType.PIPELINE_OUTAGE}
_DEMAND_TYPES = {SignalType.DEMAND_CHANGE, SignalType.WEATHER_CHANGE, SignalType.POWER_CHANGE, SignalType.LNG_CHANGE}
_STORAGE_TYPES = {SignalType.STORAGE_CHANGE}

_CATEGORY_LABELS: dict[ImpactCategory, str] = {
    ImpactCategory.PHYSICAL: "Physical Event",
    ImpactCategory.SUPPLY_DEMAND: "Supply/Demand Balance",
    ImpactCategory.STORAGE: "Storage Trajectory",
    ImpactCategory.REGIONAL: "Regional Balance",
    ImpactCategory.PRICE_CURVE: "Price/Curve",
    ImpactCategory.STRATEGY: "Strategy Implications",
    ImpactCategory.PORTFOLIO: "Portfolio Implications",
    ImpactCategory.RISK: "Risk Implications",
}

_DIRECTION_WORD = {
    SignalDirection.BULLISH: "bullish",
    SignalDirection.BEARISH: "bearish",
    SignalDirection.NEUTRAL: "neutral",
}


def _stage_text(category: ImpactCategory, signal: Signal) -> str:
    word = _DIRECTION_WORD[signal.direction]
    return {
        ImpactCategory.PHYSICAL: signal.description or signal.headline,
        ImpactCategory.SUPPLY_DEMAND: f"Consistent with a {word} shift in the domestic supply/demand balance.",
        ImpactCategory.STORAGE: "Expected to influence the storage trajectory over the signal's stated time horizon.",
        ImpactCategory.REGIONAL: (
            "Regional balance effects are directionally consistent with the broader read; not "
            "independently modeled per region in this milestone."
        ),
        ImpactCategory.PRICE_CURVE: f"Directionally {word} for the front-month price and nearby curve structure.",
        ImpactCategory.STRATEGY: "May support or caution directional/relative-value strategy positioning aligned with this read.",
        ImpactCategory.PORTFOLIO: (
            "Portfolio effect depends on existing exposure; not independently computed against live "
            "positions in this milestone."
        ),
        ImpactCategory.RISK: (
            "No independent risk-limit implication computed here; the Risk Governor remains the sole "
            "authority over any resulting trade."
        ),
    }[category]


class ImpactEngine:
    version = IMPACT_ENGINE_VERSION

    def analyze(self, signal: Signal) -> ImpactAnalysis:
        skeleton = _SKELETON_BY_SIGNAL_TYPE.get(signal.signal_type, _EVENT_SKELETON)
        chain = self._build_chain(signal, skeleton)

        supply_impact = signal.absolute_change if signal.signal_type in _SUPPLY_TYPES else None
        demand_impact = signal.absolute_change if signal.signal_type in _DEMAND_TYPES else None
        storage_impact = signal.absolute_change if signal.signal_type in _STORAGE_TYPES else None

        assumptions = [
            "Impact magnitude/confidence at each chain stage decay from the triggering signal's own "
            "materiality/confidence via a fixed per-stage factor; each stage is not independently "
            "quantified in this milestone.",
            "This causal chain reflects the signal's own directional read; it is not an independently "
            "modeled multi-factor price/curve forecast.",
        ]
        uncertainties = [
            "Downstream stages (storage/regional/curve/portfolio/risk) are qualitative, not "
            "independently computed magnitudes, in this milestone."
        ]
        alternative_interpretations = []
        if signal.signal_type in (SignalType.AGENT_DISAGREEMENT, SignalType.MODEL_DISAGREEMENT):
            alternative_interpretations.append(
                "Underlying agents/models disagree on direction; treat this chain's directional read as "
                "low-confidence rather than a consensus view."
            )

        data_sources = [c.source for c in signal.citations] or list(signal.source_ids)

        return ImpactAnalysis(
            signal_id=signal.id,
            organization_id=signal.organization_id,
            event_type=signal.signal_type,
            physical_impact=signal.description or signal.headline,
            supply_impact_bcf_day=supply_impact,
            demand_impact_bcf_day=demand_impact,
            storage_impact_bcf=storage_impact,
            expected_duration=signal.time_horizon,
            affected_geographies=[signal.geography] if signal.geography else [],
            affected_assets=list(signal.asset_ids),
            affected_markets=[signal.market],
            affected_contracts=[],
            basis_implications=(
                "Basis relationships may shift regionally; not independently modeled in this milestone."
                if ImpactCategory.REGIONAL in skeleton
                else ""
            ),
            curve_implications=_stage_text(ImpactCategory.PRICE_CURVE, signal)
            if ImpactCategory.PRICE_CURVE in skeleton
            else "",
            volatility_implications=(
                "Potential volatility implications noted but not independently modeled in this milestone."
                if signal.signal_type == SignalType.VOLATILITY_CHANGE
                else ""
            ),
            portfolio_implications=_stage_text(ImpactCategory.PORTFOLIO, signal),
            risk_implications=_stage_text(ImpactCategory.RISK, signal),
            bullish_bearish=signal.direction,
            magnitude=signal.materiality_score,
            confidence=signal.confidence,
            assumptions=assumptions,
            uncertainties=uncertainties,
            alternative_interpretations=alternative_interpretations,
            data_sources=data_sources,
            agent_contributors=list(signal.affected_agents),
            chain=chain,
        )

    def _build_chain(self, signal: Signal, skeleton: list[ImpactCategory]) -> list[ImpactEdge]:
        evidence = [f"AlphaSignal {signal.id}: {signal.headline}"]
        edges: list[ImpactEdge] = []
        previous_label = signal.headline
        for index, category in enumerate(skeleton):
            confidence = round(signal.confidence * (_STAGE_DECAY_FACTOR**index), 4)
            magnitude = round(signal.materiality_score * (_STAGE_DECAY_FACTOR**index), 2)
            edges.append(
                ImpactEdge(
                    sequence_index=index,
                    category=category,
                    from_node=previous_label,
                    to_node=_CATEGORY_LABELS[category],
                    description=_stage_text(category, signal),
                    confidence=confidence,
                    magnitude=magnitude,
                    supporting_evidence=list(evidence),
                )
            )
            previous_label = _CATEGORY_LABELS[category]
        return edges
