from __future__ import annotations

from agent_sdk import AgentOutcome, BaseAgent, LLMMessage
from schemas import AgentType, TradeIdea


class BearAgent(BaseAgent):
    """AI Investment Committee: constructs the strongest bearish interpretation."""

    agent_id = "committee.bear.v1"
    agent_name = "Bear Agent"
    agent_type = AgentType.BEAR
    version = "0.1.0"

    async def _execute(self, *, trade: TradeIdea) -> AgentOutcome:
        prompt = (
            f"Trade thesis: {trade.thesis}\nRisks: {', '.join(trade.risks) or 'none listed'}\n"
            "Construct the strongest bearish case against this trade in 2-3 sentences, using only "
            "the risks and invalidation conditions already cited — do not invent new facts."
        )
        response = await self.llm.complete(
            [LLMMessage(role="user", content=prompt)], system=self.system_instructions
        )
        case = response.content if "MOCK LLM" not in response.content else (
            f"Bear case: {', '.join(trade.risks) or 'unlisted downside risks'} could invalidate the "
            f"thesis; invalidation conditions ({', '.join(trade.invalidation_conditions) or 'the stop level'}) "
            f"cap expected loss near {trade.expected_loss}."
        )
        return AgentOutcome(
            outputs={"case": case},
            reasoning_summary=case,
            confidence=1 - trade.confidence,
            tools=["committee.bear.reason"],
        )
