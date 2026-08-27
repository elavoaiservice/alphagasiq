from __future__ import annotations

from agent_sdk import AgentOutcome, BaseAgent, LLMMessage
from fundamentals_service.power_burn import PowerMarketState, estimate_power_burn_bcf_d
from schemas import AgentStatus, AgentType, Citation, DataClassification, DataSourceRef


class PowerMarketAgent(BaseAgent):
    """Fundamental Research Team: ISO/RTO load and generation mix, converted to an
    estimated gas-fired power-burn demand figure (`fundamentals_service.power_burn`)."""

    agent_id = "fundamentals.power_market.v1"
    agent_name = "Power Market Agent"
    agent_type = AgentType.POWER_MARKET
    version = "0.1.0"

    async def _execute(self, *, markets: list[PowerMarketState], is_simulated: bool = True) -> AgentOutcome:
        if not markets:
            return AgentOutcome(
                status=AgentStatus.SKIPPED,
                reasoning_summary="No ISO/RTO market data available for power-burn analysis.",
            )

        burn_by_iso = {m.iso: estimate_power_burn_bcf_d(m) for m in markets}
        total_burn_bcf_d = round(sum(burn_by_iso.values()), 3)
        total_load_gw = round(sum(m.load_gw for m in markets), 2)
        total_gas_generation_gw = round(sum(m.gas_generation_gw for m in markets), 2)
        gas_share_of_generation = (
            round(total_gas_generation_gw / total_load_gw, 4) if total_load_gw else 0.0
        )

        outputs = {
            "total_power_burn_bcf_d": total_burn_bcf_d,
            "burn_by_iso_bcf_d": burn_by_iso,
            "total_load_gw": total_load_gw,
            "gas_share_of_generation": gas_share_of_generation,
        }

        prompt = (
            f"Estimated gas-fired power burn is {total_burn_bcf_d:.2f} Bcf/d across "
            f"{len(markets)} ISO/RTOs, with gas supplying {gas_share_of_generation:.0%} of "
            f"{total_load_gw:.1f} GW of total load. Summarize the power-burn picture in two "
            "sentences for a trading desk."
        )
        llm_response = await self.llm.complete([LLMMessage(role="user", content=prompt)])

        classification = DataClassification.SIMULATED if is_simulated else DataClassification.PUBLIC
        reasoning = (
            f"Gas-fired power burn estimated at {total_burn_bcf_d:.2f} Bcf/d "
            f"({gas_share_of_generation:.0%} of total generation across {len(markets)} ISO/RTOs). "
            f"{llm_response.content}"
        )

        return AgentOutcome(
            outputs=outputs,
            reasoning_summary=reasoning,
            confidence=0.6,
            tools=["fundamentals_service.power_burn.estimate_power_burn_bcf_d"],
            data_sources=[
                DataSourceRef(provider_id="iso_rto_public", series_id=m.iso, classification=classification)
                for m in markets
            ],
            citations=[
                Citation(source="ISO/RTO market roster (seed/simulated)", reference="fundamentals/power", classification=classification)
            ],
        )
