from __future__ import annotations

from agent_sdk import AgentOutcome, BaseAgent, LLMMessage
from fundamentals_service.lng import LNGTerminalState, compute_netback
from schemas import AgentStatus, AgentType, Citation, DataClassification, DataSourceRef


class LNGAgent(BaseAgent):
    """Fundamental Research Team: LNG terminal feedgas/utilization and the
    Henry-Hub-to-TTF netback that determines whether export is currently
    economically incentivized (`fundamentals_service.lng`)."""

    agent_id = "fundamentals.lng.v1"
    agent_name = "LNG Agent"
    agent_type = AgentType.LNG
    version = "0.1.0"

    async def _execute(
        self,
        *,
        terminals: list[LNGTerminalState],
        henry_hub_price: float,
        ttf_price: float | None = None,
        is_simulated: bool = True,
    ) -> AgentOutcome:
        if not terminals:
            return AgentOutcome(
                status=AgentStatus.SKIPPED,
                reasoning_summary="No LNG terminal data available for feedgas analysis.",
            )

        total_capacity = sum(t.capacity_bcf_d for t in terminals)
        total_feedgas = sum(t.feedgas_bcf_d for t in terminals)
        average_utilization = round(total_feedgas / total_capacity, 4) if total_capacity else 0.0
        terminals_in_outage = [t.name for t in terminals if t.outage_status != "NONE"]
        terminals_in_maintenance = [t.name for t in terminals if t.maintenance_status != "NORMAL"]

        netback = None
        if ttf_price is not None:
            netback = compute_netback(destination="TTF", henry_hub_price=henry_hub_price, destination_price=ttf_price)

        outputs = {
            "total_capacity_bcf_d": round(total_capacity, 3),
            "total_feedgas_bcf_d": round(total_feedgas, 3),
            "average_utilization": average_utilization,
            "terminals_in_outage": terminals_in_outage,
            "terminals_in_maintenance": terminals_in_maintenance,
            "netback_ttf_usd_mmbtu": netback.netback_usd_mmbtu if netback else None,
            "export_incentivized": netback.export_incentivized if netback else None,
        }

        netback_sentence = (
            f" TTF netback is {netback.netback_usd_mmbtu:+.2f} $/MMBtu "
            f"({'export-incentivized' if netback.export_incentivized else 'not currently export-incentivized'})."
            if netback is not None
            else ""
        )
        prompt = (
            f"LNG feedgas is running at {total_feedgas:.2f} Bcf/d, {average_utilization:.0%} of "
            f"{total_capacity:.2f} Bcf/d nameplate capacity across {len(terminals)} terminals."
            f"{netback_sentence} Summarize the LNG demand picture in two sentences for a trading desk."
        )
        llm_response = await self.llm.complete([LLMMessage(role="user", content=prompt)])

        classification = DataClassification.SIMULATED if is_simulated else DataClassification.PUBLIC
        reasoning = (
            f"LNG feedgas utilization is {average_utilization:.0%} across {len(terminals)} terminals"
            + (f"; {len(terminals_in_outage)} in outage" if terminals_in_outage else "")
            + (f"; TTF netback {netback.netback_usd_mmbtu:+.2f} $/MMBtu" if netback is not None else "")
            + f". {llm_response.content}"
        )

        return AgentOutcome(
            outputs=outputs,
            reasoning_summary=reasoning,
            confidence=0.65 if not terminals_in_outage else 0.5,
            tools=["fundamentals_service.lng.compute_netback"],
            data_sources=[DataSourceRef(provider_id="mock_ice", series_id="TTF.FRONT_MONTH", classification=classification)],
            citations=[Citation(source="LNG terminal roster (seed/simulated)", reference="fundamentals/lng", classification=classification)],
        )
