"""AlphaMemory(TM) (docs/alpha-intelligence.md section 8): builds a durable
`MemoryRecord` from a closed trade's already-computed lifecycle objects, and
proposes a deterministic, template-based lesson from its outcome. Pure functions --
no DB/LLM/event-bus access, same design philosophy as every other engine in this
package.

Milestone 5 is honest about scope: `MemoryBuilder` only links what is already,
unambiguously `trade_id`-linked in this codebase (`TradeIdea`,
`InvestmentCommitteeDecision`, `RiskCheckResult`, `PostTradeAnalysis`, and the
`PriceForecast` attached at trade creation, if any). It never attempts to correlate
a trade back to the `Signal`/`ConsensusView`/`ScenarioRunResult` that may have
informed it -- no such link exists in the data model today, and guessing one via
time-window correlation would misrepresent an unverified guess as traceable
evidence. `LessonEngine` reuses `PostTradeAnalysis.quadrant` (never recomputes it)
and drafts a lesson via a fixed template keyed off that quadrant -- not an LLM, the
same "no LLM in the engine path" discipline as every other Alpha* engine.
"""

from __future__ import annotations

from schemas import (
    InvestmentCommitteeDecision,
    LessonProposal,
    MemoryRecord,
    MemoryType,
    OutcomeQuadrant,
    PostTradeAnalysis,
    PriceForecast,
    RiskCheckResult,
    TradeIdea,
)

_LESSON_TEMPLATES: dict[OutcomeQuadrant, str] = {
    OutcomeQuadrant.GOOD_DECISION_GOOD_OUTCOME: (
        "Process validated: the committee consensus and risk gating that approved this trade produced a "
        "good outcome -- keep using this thesis pattern when similar catalysts recur."
    ),
    OutcomeQuadrant.GOOD_DECISION_BAD_OUTCOME: (
        "Process was sound (committee consensus + risk-approved); the loss reflects normal variance, not a "
        "process failure -- do not tighten thresholds in response to this trade alone."
    ),
    OutcomeQuadrant.BAD_DECISION_GOOD_OUTCOME: (
        "Profitable, but the committee/risk record does not support calling this a well-reasoned decision -- "
        "review why weak consensus or risk gating let this trade through, and do not treat the profit as "
        "validation of the process."
    ),
    OutcomeQuadrant.BAD_DECISION_BAD_OUTCOME: (
        "Both the decision and the outcome were poor -- review the committee consensus threshold and risk "
        "gating that allowed this trade, since the process failure and the loss point the same direction."
    ),
}


class MemoryBuilder:
    def build_decision_memory(
        self,
        *,
        trade: TradeIdea,
        committee: InvestmentCommitteeDecision,
        risk_check: RiskCheckResult,
        post_trade: PostTradeAnalysis,
        forecast: PriceForecast | None = None,
        organization_id: str | None = None,
    ) -> MemoryRecord:
        structured_context: dict = {
            "strategy": trade.strategy,
            "instrument": trade.instrument,
            "direction": trade.direction.value,
            "thesis": trade.thesis,
            "committee_consensus_score": committee.consensus_score,
            "risk_verdict": risk_check.verdict.value,
            "thesis_accuracy": post_trade.thesis_accuracy,
            "timing_accuracy": post_trade.timing_accuracy,
            "risk_accuracy": post_trade.risk_accuracy,
            "expected_outcome": post_trade.expected_outcome,
            "actual_outcome": post_trade.actual_outcome,
        }
        if forecast is not None:
            structured_context["quant_forecast"] = {
                "instrument": forecast.instrument,
                "horizon": forecast.horizon.value,
                "up_probability": forecast.up_probability,
                "confidence": forecast.confidence,
            }

        return MemoryRecord(
            organization_id=organization_id,
            memory_type=MemoryType.DECISION_MEMORY,
            trade_id=trade.trade_id,
            market=trade.instrument,
            strategy=trade.strategy,
            title=f"{trade.strategy} on {trade.instrument} ({post_trade.quadrant.value})",
            summary=post_trade.lessons,
            outcome_quadrant=post_trade.quadrant,
            structured_context=structured_context,
            tags=[trade.strategy, trade.instrument, post_trade.quadrant.value],
        )


class LessonEngine:
    def propose(self, memory: MemoryRecord, *, organization_id: str | None = None) -> LessonProposal | None:
        """Returns `None` when the memory has no outcome to learn from yet (only
        `DECISION_MEMORY` records with a resolved `outcome_quadrant` ever produce a
        lesson proposal in Milestone 5)."""
        if memory.outcome_quadrant is None:
            return None
        template = _LESSON_TEMPLATES[memory.outcome_quadrant]
        return LessonProposal(
            organization_id=organization_id,
            memory_record_id=memory.id,
            proposed_lesson=template,
            rationale=(
                f"Derived from {memory.title}'s outcome quadrant ({memory.outcome_quadrant.value}) -- "
                f"see the linked memory record's structured_context for the underlying committee/risk/"
                f"post-trade figures this template was selected from."
            ),
        )
