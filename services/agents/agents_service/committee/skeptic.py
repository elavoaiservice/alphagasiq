from __future__ import annotations

from agent_sdk import AgentOutcome, BaseAgent, LLMMessage
from schemas import AgentType, TradeIdea


class SkepticAgent(BaseAgent):
    """AI Investment Committee: actively attempts to falsify the primary thesis rather
    than just presenting the opposing side (that's the Bear Agent's job)."""

    agent_id = "committee.skeptic.v1"
    agent_name = "Skeptic Agent"
    agent_type = AgentType.SKEPTIC
    version = "0.1.0"

    async def _execute(self, *, trade: TradeIdea) -> AgentOutcome:
        unresolved: list[str] = []
        if trade.probability_success < 0.55:
            unresolved.append("Stated probability of success is not much better than a coin flip.")
        if not trade.invalidation_conditions:
            unresolved.append("No explicit invalidation conditions were provided.")
        if not trade.source_citations and not trade.supporting_data:
            unresolved.append("No supporting data or citations were attached to this thesis.")
        if trade.expected_return < abs(trade.expected_loss):
            unresolved.append("Expected return does not clearly exceed expected loss.")

        prompt = (
            f"Attempt to falsify this thesis: {trade.thesis}. What single piece of evidence, if it "
            "turned out to be wrong or stale, would break the trade? One or two sentences."
        )
        response = await self.llm.complete([LLMMessage(role="user", content=prompt)])
        case = response.content if "MOCK LLM" not in response.content else (
            "Skeptic case: "
            + (
                " ".join(unresolved)
                if unresolved
                else "No structural weaknesses found in the stated thesis, but confirm underlying "
                "data freshness before relying on it."
            )
        )

        return AgentOutcome(
            outputs={"case": case, "unresolved_questions": unresolved},
            reasoning_summary=case,
            confidence=0.5,
            tools=["committee.skeptic.falsify"],
        )
