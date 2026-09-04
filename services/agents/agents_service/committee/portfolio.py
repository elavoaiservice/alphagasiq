from __future__ import annotations

from agent_sdk import AgentOutcome, BaseAgent
from schemas import AgentType, Direction, TradeIdea


class PortfolioAgent(BaseAgent):
    """AI Investment Committee: determines how a proposed trade interacts with
    existing positions (adds concentration? offsets existing exposure? correlated?)."""

    agent_id = "committee.portfolio.v1"
    agent_name = "Portfolio Agent"
    agent_type = AgentType.PORTFOLIO
    version = "0.1.0"

    async def _execute(
        self,
        *,
        trade: TradeIdea,
        existing_positions: dict[str, float],  # instrument -> signed quantity
        gross_exposure_limit_fraction: float = 0.35,
    ) -> AgentOutcome:
        existing_same_instrument = existing_positions.get(trade.instrument, 0.0)
        proposed_signed = 1 if trade.direction == Direction.LONG else -1

        adds_to_existing = (existing_same_instrument > 0 and proposed_signed > 0) or (
            existing_same_instrument < 0 and proposed_signed < 0
        )
        offsets_existing = existing_same_instrument != 0 and not adds_to_existing

        total_gross = sum(abs(q) for q in existing_positions.values())
        instrument_share = (
            abs(existing_same_instrument) / total_gross if total_gross > 0 else 0.0
        )

        if offsets_existing:
            effect = "REDUCES existing exposure (offsetting trade)"
        elif adds_to_existing and instrument_share > gross_exposure_limit_fraction:
            effect = "INCREASES an already-concentrated position"
        elif adds_to_existing:
            effect = "ADDS to existing exposure in the same direction"
        else:
            effect = "OPENS new, uncorrelated exposure"

        return AgentOutcome(
            outputs={
                "existing_position_in_instrument": existing_same_instrument,
                "instrument_share_of_gross": round(instrument_share, 3),
                "portfolio_effect": effect,
            },
            reasoning_summary=(
                f"Proposed {trade.direction.value} {trade.instrument} {effect.lower()}; "
                f"current instrument share of gross exposure is {instrument_share:.1%}."
            ),
            confidence=0.8,
            tools=["portfolio.exposure_check"],
        )
