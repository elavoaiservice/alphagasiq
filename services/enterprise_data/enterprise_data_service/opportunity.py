"""`EnterpriseOpportunityEngine` (docs/alpha-intelligence.md section 11.7,
Milestone 10): cross-references an organization's own proprietary position data
against the Alpha Intelligence Layer's signals/consensus views to draft candidate
`EnterpriseOpportunity` records -- the "Opportunity Engine" from the original
plan. Every candidate is always human-reviewed before it means anything
(`EnterpriseOpportunityStatus.PENDING` until an admin approves/rejects it via
`POST /alpha/enterprise/opportunities/{id}/review`) -- nothing here is ever
auto-executed into a trade or position change, the same posture
`AlphaMemory`'s `LessonEngine`/`LessonProposal` already establishes.

Pure -- no DB/LLM/event-bus access, the same discipline as every other engine
in this codebase (`risk_service.governor.RiskGovernor`,
`alpha_service.trading_integration.AlphaCorroborationEngine`, etc.).

Detects exactly two opportunity shapes, deliberately not an open-ended
taxonomy:

- `HEDGE_MISALIGNED_POSITION`: the organization holds a position in a market
  where the current `ConsensusView` leans meaningfully the opposite direction
  at high confidence.
- `NEW_POSITION_HIGH_CONVICTION_SIGNAL`: a high-materiality, clearly-directional
  `Signal` exists for a market the organization holds no position in at all.

Provisional decisions (revisit once real customer position data exists, same
"documented judgment call, not derived from data" discipline as AlphaSignal's
materiality weights):

- `min_materiality=65.0` -- a few points above AlphaSignal's own
  `DEFAULT_MATERIALITY_THRESHOLD` (60.0), since this drives a human-facing
  recommendation about real capital rather than an internal annotation.
- `min_consensus_confidence=0.6` / `min_consensus_divergence=0.3` (the gap
  between `bull_probability` and `bear_probability`) for flagging a misaligned
  position.
- A position record's `row_data` is assumed to carry `market` or `instrument`
  (required) and optionally `direction` (`"LONG"`/`"SHORT"`) and `quantity` --
  there is no enforced schema for enterprise records (docs/alpha-intelligence.md
  section 11.4: they're stored as an opaque JSON blob), so a record missing a
  recognizable market/instrument field is skipped defensively, never guessed
  at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from schemas import ConsensusView, Signal, SignalDirection

DEFAULT_MIN_MATERIALITY = 65.0
DEFAULT_MIN_CONSENSUS_CONFIDENCE = 0.6
DEFAULT_MIN_CONSENSUS_DIVERGENCE = 0.3


@dataclass
class EnterprisePosition:
    """A position parsed from one entitled `POSITION`/`PORTFOLIO`-domain
    `EnterpriseRecordRow`. See module docstring for the assumed `row_data`
    shape and why a record that doesn't match it is skipped rather than
    guessed at."""

    dataset_id: str
    record_id: str
    market: str
    direction: str | None = None
    quantity: float | None = None

    @staticmethod
    def from_record(*, dataset_id: str, record_id: str, row_data: dict[str, Any]) -> "EnterprisePosition | None":
        market = row_data.get("market") or row_data.get("instrument")
        if not market or not isinstance(market, str):
            return None
        direction = row_data.get("direction")
        if isinstance(direction, str):
            direction = direction.strip().upper()
            if direction not in ("LONG", "SHORT"):
                direction = None
        else:
            direction = None
        quantity = row_data.get("quantity")
        if not isinstance(quantity, (int, float)):
            quantity = None
        return EnterprisePosition(
            dataset_id=dataset_id, record_id=record_id, market=market, direction=direction, quantity=quantity
        )


@dataclass
class OpportunityCandidate:
    opportunity_type: str
    market: str
    title: str
    summary: str
    confidence: float
    supporting_signal_ids: list[str] = field(default_factory=list)
    supporting_consensus_id: str | None = None
    related_dataset_id: str | None = None
    related_record_id: str | None = None


class EnterpriseOpportunityEngine:
    def generate(
        self,
        *,
        positions: list[EnterprisePosition],
        signals: list[Signal],
        consensus_views: list[ConsensusView],
        min_materiality: float = DEFAULT_MIN_MATERIALITY,
        min_consensus_confidence: float = DEFAULT_MIN_CONSENSUS_CONFIDENCE,
        min_consensus_divergence: float = DEFAULT_MIN_CONSENSUS_DIVERGENCE,
    ) -> list[OpportunityCandidate]:
        candidates: list[OpportunityCandidate] = []
        positions_by_market: dict[str, list[EnterprisePosition]] = {}
        for pos in positions:
            positions_by_market.setdefault(pos.market, []).append(pos)

        latest_consensus_by_market: dict[str, ConsensusView] = {}
        for view in consensus_views:
            existing = latest_consensus_by_market.get(view.market)
            if existing is None or view.created_at > existing.created_at:
                latest_consensus_by_market[view.market] = view

        candidates.extend(
            self._hedge_candidates(
                positions_by_market, latest_consensus_by_market, min_consensus_confidence, min_consensus_divergence
            )
        )
        candidates.extend(
            self._new_position_candidates(positions_by_market, signals, min_materiality)
        )
        return candidates

    @staticmethod
    def _hedge_candidates(
        positions_by_market: dict[str, list[EnterprisePosition]],
        latest_consensus_by_market: dict[str, ConsensusView],
        min_consensus_confidence: float,
        min_consensus_divergence: float,
    ) -> list[OpportunityCandidate]:
        out: list[OpportunityCandidate] = []
        for market, market_positions in positions_by_market.items():
            view = latest_consensus_by_market.get(market)
            if view is None or view.confidence < min_consensus_confidence:
                continue
            divergence = view.bear_probability - view.bull_probability
            leans_bearish = divergence >= min_consensus_divergence
            leans_bullish = -divergence >= min_consensus_divergence
            if not leans_bearish and not leans_bullish:
                continue
            for pos in market_positions:
                misaligned = (pos.direction == "LONG" and leans_bearish) or (
                    pos.direction == "SHORT" and leans_bullish
                )
                if not misaligned:
                    continue
                out.append(
                    OpportunityCandidate(
                        opportunity_type="HEDGE_MISALIGNED_POSITION",
                        market=market,
                        title=f"{pos.direction.title()} position in {market} runs counter to AlphaConsensus",
                        summary=(
                            f"Your {pos.direction.lower()} position in {market} is misaligned with the current "
                            f"consensus view ({view.agreement_label} agreement, {view.agent_count} agent(s)): "
                            f"bull {view.bull_probability:.0%} / bear {view.bear_probability:.0%}, "
                            f"confidence {view.confidence:.0%}. Consider reviewing whether a hedge is warranted."
                        ),
                        confidence=view.confidence,
                        supporting_consensus_id=str(view.id),
                        related_dataset_id=pos.dataset_id,
                        related_record_id=pos.record_id,
                    )
                )
        return out

    @staticmethod
    def _new_position_candidates(
        positions_by_market: dict[str, list[EnterprisePosition]],
        signals: list[Signal],
        min_materiality: float,
    ) -> list[OpportunityCandidate]:
        out: list[OpportunityCandidate] = []
        signals_by_market: dict[str, list[Signal]] = {}
        for sig in signals:
            if sig.materiality_score < min_materiality:
                continue
            if sig.direction not in (SignalDirection.BULLISH, SignalDirection.BEARISH):
                continue
            signals_by_market.setdefault(sig.market, []).append(sig)

        for market, market_signals in signals_by_market.items():
            if market in positions_by_market:
                continue  # Already have a position here -- that's the hedge case, not a new-position one.
            top_signal = max(market_signals, key=lambda s: s.materiality_score)
            out.append(
                OpportunityCandidate(
                    opportunity_type="NEW_POSITION_HIGH_CONVICTION_SIGNAL",
                    market=market,
                    title=f"High-conviction {top_signal.direction.value.lower()} signal in {market} with no existing position",
                    summary=(
                        f"AlphaSignal detected a {top_signal.direction.value.lower()} signal in {market} "
                        f"(materiality {top_signal.materiality_score:.0f}, confidence {top_signal.confidence:.0%}): "
                        f"{top_signal.headline}. Your organization holds no position in this market."
                    ),
                    confidence=top_signal.confidence,
                    supporting_signal_ids=[str(s.id) for s in market_signals],
                )
            )
        return out
