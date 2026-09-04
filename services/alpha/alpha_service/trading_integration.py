"""Wires AlphaSignal(TM)/AlphaConsensus(TM) into the Chief Trading Agent's own
trade-generation pipeline (docs/alpha-intelligence.md section 10, Milestone 7).

Every Alpha* component built through Milestone 6 runs strictly *after* a
`TradeIdea` already exists -- a parallel, downstream analysis layer that never
feeds back into trade generation itself. `AlphaCorroborationEngine` is the first
integration point that closes that loop: it cross-checks a freshly-generated
`TradeIdea` against this cycle's AlphaSignal output and the latest AlphaConsensus
view, and returns annotations meant to be merged onto the trade *before* the
Investment Committee deliberates on it -- so `BullAgent` (reads `trade.catalysts`)
and `SkepticAgent` (reads `trade.source_citations`/`trade.supporting_data`)
genuinely see the Alpha Intelligence Layer's own conclusions, not just a cosmetic
label.

Pure -- no DB/LLM/event-bus access, the same discipline as every other engine in
this package. Deliberately conservative: a signal only corroborates or cautions a
trade when it is a) at-or-above `DEFAULT_MATERIALITY_THRESHOLD` and b) has a clear
directional lean (`SignalDirection.BULLISH`/`BEARISH`) matched against the trade's
own `Direction` (`LONG`/`SHORT`). A `SPREAD` trade or a `NEUTRAL` signal is never
scored as aligned or opposed -- there is no principled directional read for either,
so neither is guessed at."""

from __future__ import annotations

from dataclasses import dataclass, field

from schemas import ConsensusView, Direction, Signal, SignalDirection, TradeIdea

from .materiality import DEFAULT_MATERIALITY_THRESHOLD

_ALIGNED_SIGNAL_DIRECTION: dict[Direction, SignalDirection] = {
    Direction.LONG: SignalDirection.BULLISH,
    Direction.SHORT: SignalDirection.BEARISH,
}
_OPPOSED_SIGNAL_DIRECTION: dict[Direction, SignalDirection] = {
    Direction.LONG: SignalDirection.BEARISH,
    Direction.SHORT: SignalDirection.BULLISH,
}


@dataclass
class TradeCorroboration:
    """Additions to merge onto a `TradeIdea`'s own list fields -- never a
    replacement, so nothing the strategy agent already said is lost."""

    additional_catalysts: list[str] = field(default_factory=list)
    additional_supporting_data: list[str] = field(default_factory=list)
    additional_citations: list[str] = field(default_factory=list)
    additional_risks: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (
            self.additional_catalysts
            or self.additional_supporting_data
            or self.additional_citations
            or self.additional_risks
        )


class AlphaCorroborationEngine:
    def corroborate(
        self,
        *,
        trade: TradeIdea,
        signals: list[Signal],
        consensus_view: ConsensusView | None,
    ) -> TradeCorroboration:
        result = TradeCorroboration()
        aligned_direction = _ALIGNED_SIGNAL_DIRECTION.get(trade.direction)
        opposed_direction = _OPPOSED_SIGNAL_DIRECTION.get(trade.direction)
        if aligned_direction is None:
            return result  # SPREAD trades: no principled directional read, skip.

        for sig in signals:
            if sig.materiality_score < DEFAULT_MATERIALITY_THRESHOLD:
                continue
            if sig.direction == aligned_direction:
                result.additional_catalysts.append(
                    f"AlphaSignal: {sig.headline} (materiality {sig.materiality_score:.0f})"
                )
                result.additional_citations.append(f"alpha_signal:{sig.id}")
            elif sig.direction == opposed_direction:
                result.additional_risks.append(
                    f"AlphaSignal caution: {sig.headline} runs counter to this trade's direction "
                    f"(materiality {sig.materiality_score:.0f})"
                )
                result.additional_citations.append(f"alpha_signal:{sig.id}")

        if consensus_view is not None:
            leans_bullish = consensus_view.bull_probability > consensus_view.bear_probability
            leans_bearish = consensus_view.bear_probability > consensus_view.bull_probability
            trade_is_long = trade.direction == Direction.LONG
            if (trade_is_long and leans_bullish) or (not trade_is_long and leans_bearish):
                result.additional_supporting_data.append(
                    f"AlphaConsensus agrees ({consensus_view.agreement_label} agreement, "
                    f"{consensus_view.agent_count} agent(s)): bull {consensus_view.bull_probability:.0%} / "
                    f"bear {consensus_view.bear_probability:.0%}"
                )
                result.additional_citations.append(f"alpha_consensus:{consensus_view.id}")
            elif (trade_is_long and leans_bearish) or (not trade_is_long and leans_bullish):
                dissent = (
                    f" Dissenting agents: {', '.join(consensus_view.dissenting_agents)}."
                    if consensus_view.dissenting_agents
                    else ""
                )
                result.additional_risks.append(
                    "AlphaConsensus caution: agent consensus leans the opposite direction "
                    f"(bull {consensus_view.bull_probability:.0%} / bear {consensus_view.bear_probability:.0%})."
                    f"{dissent}"
                )
                result.additional_citations.append(f"alpha_consensus:{consensus_view.id}")

        return result
