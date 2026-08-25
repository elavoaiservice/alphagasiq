from __future__ import annotations

from agent_sdk import AgentOutcome, BaseAgent, LLMMessage
from quant_service import calendar_spread_signal, hh_ttf_netback_signal
from schemas import AgentType, Citation, DataClassification


class RelativeValueAgent(BaseAgent):
    """Quantitative Team: cross-contract/cross-market mispricing signals
    (docs/architecture.md "Relative Value Agent"). Computes the HH-TTF netback signal
    and the M1-M2 calendar-spread-vs-cost-of-carry signal; see
    `quant_service.relative_value` for the (illustrative, not yet calibrated)
    thresholds behind each.
    """

    agent_id = "quant.relative_value.v1"
    agent_name = "Relative Value Agent"
    agent_type = AgentType.RELATIVE_VALUE
    version = "0.1.0"

    async def _execute(
        self,
        *,
        henry_hub_price: float,
        ttf_price: float,
        m1_price: float,
        m2_price: float,
        is_simulated: bool = True,
    ) -> AgentOutcome:
        netback_signal = hh_ttf_netback_signal(henry_hub_price=henry_hub_price, ttf_price=ttf_price)
        spread_signal = calendar_spread_signal(m1_price=m1_price, m2_price=m2_price)

        classification = DataClassification.SIMULATED if is_simulated else DataClassification.PUBLIC
        prompt = (
            f"HH-TTF netback signal: {netback_signal.direction} ({netback_signal.rationale}). "
            f"Calendar spread signal: {spread_signal.direction} ({spread_signal.rationale}). "
            "One sentence combining both for a trading desk."
        )
        llm_response = await self.llm.complete([LLMMessage(role="user", content=prompt)])
        reasoning = (
            f"HH-TTF netback: {netback_signal.direction}. Calendar spread: {spread_signal.direction}. "
            f"{llm_response.content}"
        )

        return AgentOutcome(
            outputs={
                "hh_ttf_netback": netback_signal.model_dump(mode="json"),
                "calendar_spread": spread_signal.model_dump(mode="json"),
            },
            reasoning_summary=reasoning,
            confidence=round((netback_signal.confidence + spread_signal.confidence) / 2, 3),
            tools=["quant_service.relative_value"],
            citations=[Citation(source="quant_service relative value engine", reference="hh_ttf_netback + calendar_spread", classification=classification)],
        )
