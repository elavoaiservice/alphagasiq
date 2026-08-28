from __future__ import annotations

from agent_sdk import AgentOutcome, BaseAgent, LLMMessage
from schemas import AgentType, TradeIdea


class BullAgent(BaseAgent):
    """AI Investment Committee: constructs the strongest bullish interpretation of a
    proposed trade idea, grounded only in the trade's own citations/supporting data."""

    agent_id = "committee.bull.v1"
    agent_name = "Bull Agent"
    agent_type = AgentType.BULL
    version = "0.1.0"

    async def _execute(self, *, trade: TradeIdea) -> AgentOutcome:
        prompt = (
            f"Trade thesis: {trade.thesis}\nCatalysts: {', '.join(trade.catalysts) or 'none listed'}\n"
            "Construct the strongest bullish case for this trade in 2-3 sentences, using only the "
            "catalysts and supporting data already cited — do not invent new facts."
        )
        response = await self.llm.complete(
            [LLMMessage(role="user", content=prompt)], system=self.system_instructions
        )
        case = response.content if "MOCK LLM" not in response.content else (
            f"Bull case: {trade.thesis} is reinforced by {', '.join(trade.catalysts) or 'the stated catalysts'}, "
            f"supporting a {trade.probability_success:.0%} probability of reaching the {trade.target} target."
        )
        return AgentOutcome(
            outputs={"case": case},
            reasoning_summary=case,
            confidence=trade.confidence,
            tools=["committee.bull.reason"],
        )
