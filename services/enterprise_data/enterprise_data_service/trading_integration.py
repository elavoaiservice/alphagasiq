"""Wires an organization's own proprietary position data into the Chief Trading
Agent's trade-generation pipeline (docs/alpha-intelligence.md section 11, Milestone
10 follow-up). Mirrors `alpha_service.trading_integration.AlphaCorroborationEngine`
exactly, one level down: where that engine cross-checks a trade against the
platform-wide AlphaSignal/AlphaConsensus view, this one cross-checks it against one
organization's own `EnterprisePosition` holdings, so an enterprise customer's book --
not just abstract market signals -- becomes part of what the Investment Committee
reasons about. `BullAgent` (reads `trade.catalysts`/`supporting_data`) and
`SkepticAgent` (reads `trade.source_citations`/`risks`) genuinely see whether this
trade reinforces or fights the organization's existing positions, not just a
cosmetic label.

Pure -- no DB/LLM/event-bus access, the same discipline as every other engine in
this codebase. Deliberately conservative: a position only corroborates or cautions a
trade when both share the same `market`/`instrument` and the position has a
recognizable `direction` (`EnterprisePosition.from_record` already discards anything
else) -- a `SPREAD` trade or a position with no parseable direction is never scored
as aligned or opposed, there is no principled directional read for either."""

from __future__ import annotations

from dataclasses import dataclass, field

from schemas import Direction, TradeIdea

from .opportunity import EnterprisePosition


@dataclass
class EnterpriseCorroboration:
    """Additions to merge onto a `TradeIdea`'s own list fields -- never a
    replacement, so nothing the strategy agent already said is lost. Mirrors
    `alpha_service.trading_integration.TradeCorroboration`'s shape."""

    additional_supporting_data: list[str] = field(default_factory=list)
    additional_citations: list[str] = field(default_factory=list)
    additional_risks: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.additional_supporting_data or self.additional_citations or self.additional_risks)


class EnterpriseCorroborationEngine:
    def corroborate(
        self,
        *,
        trade: TradeIdea,
        positions: list[EnterprisePosition],
    ) -> EnterpriseCorroboration:
        result = EnterpriseCorroboration()
        if trade.direction not in (Direction.LONG, Direction.SHORT):
            return result  # SPREAD trades: no principled directional read, skip.

        trade_direction = trade.direction.value
        for pos in positions:
            if pos.market != trade.instrument or pos.direction is None:
                continue
            quantity_note = f" ({pos.quantity:g} units)" if pos.quantity is not None else ""
            citation = f"enterprise_position:{pos.dataset_id}:{pos.record_id}"
            if pos.direction == trade_direction:
                result.additional_supporting_data.append(
                    f"Your organization already holds a {pos.direction.lower()} position in "
                    f"{pos.market}{quantity_note}, consistent with this trade idea."
                )
                result.additional_citations.append(citation)
            else:
                result.additional_risks.append(
                    f"Your organization holds an opposing {pos.direction.lower()} position in "
                    f"{pos.market}{quantity_note} -- this trade would work against your existing book."
                )
                result.additional_citations.append(citation)

        return result
