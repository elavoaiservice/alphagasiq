from __future__ import annotations

from agent_sdk import LLMProvider
from schemas import InvestmentCommitteeDecision, ObservationDraft, RecommendedAction, TradeIdea

from .bear import BearAgent
from .bull import BullAgent
from .data_integrity import DataIntegrityAgent
from .portfolio import PortfolioAgent
from .skeptic import SkepticAgent


class InvestmentCommittee:
    """Runs every committee agent against a proposed `TradeIdea` and produces the
    `InvestmentCommitteeDecision` record. This is deliberation, not authority: the
    committee's `recommended_action` still has to clear the independent Risk Governor
    and human approval before anything becomes a paper trade.
    """

    def __init__(self, llm: LLMProvider | None = None):
        self.bull = BullAgent(llm=llm)
        self.bear = BearAgent(llm=llm)
        self.skeptic = SkepticAgent(llm=llm)
        self.data_integrity = DataIntegrityAgent(llm=llm)
        self.portfolio = PortfolioAgent(llm=llm)

    async def deliberate(
        self,
        *,
        trade: TradeIdea,
        supporting_observations: list[ObservationDraft],
        freshness_limits_seconds: dict[str, int],
        existing_positions: dict[str, float],
    ) -> InvestmentCommitteeDecision:
        bull_result = await self.bull.run(trade=trade)
        bear_result = await self.bear.run(trade=trade)
        skeptic_result = await self.skeptic.run(trade=trade)
        integrity_result = await self.data_integrity.run(
            observations=supporting_observations, freshness_limits_seconds=freshness_limits_seconds
        )
        portfolio_result = await self.portfolio.run(trade=trade, existing_positions=existing_positions)

        unresolved = list(skeptic_result.outputs.get("unresolved_questions", []))
        data_issues = integrity_result.outputs.get("issues", [])

        consensus_score = round(
            0.4 * trade.probability_success
            + 0.3 * trade.confidence
            + 0.3 * (integrity_result.confidence or 1.0),
            3,
        )

        if data_issues:
            action = RecommendedAction.WAIT_FOR_MORE_DATA
        elif unresolved and consensus_score < 0.5:
            action = RecommendedAction.REJECT
        elif consensus_score < 0.45:
            action = RecommendedAction.REJECT
        elif consensus_score < 0.6:
            action = RecommendedAction.REDUCE_SIZE
        else:
            action = RecommendedAction.APPROVE_FOR_REVIEW

        return InvestmentCommitteeDecision(
            original_trade=trade,
            bull_case=bull_result.outputs.get("case", bull_result.reasoning_summary),
            bear_case=bear_result.outputs.get("case", bear_result.reasoning_summary),
            skeptic_case=skeptic_result.outputs.get("case", skeptic_result.reasoning_summary),
            data_quality_assessment=integrity_result.reasoning_summary,
            portfolio_effect=portfolio_result.reasoning_summary,
            consensus_score=consensus_score,
            unresolved_questions=unresolved + data_issues,
            recommended_action=action,
        )
