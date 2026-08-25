from __future__ import annotations

from agent_sdk import AgentOutcome, BaseAgent, LLMMessage
from schemas import AgentStatus, AgentType, Citation, DataClassification, DataSourceRef, GasBalanceDaily


class DemandAgent(BaseAgent):
    """Fundamental Research Team: res/comm, industrial, Mexico exports, other demand
    (power burn and LNG feedgas are covered by the Power Market and LNG agents but are
    included here too since they roll into total demand)."""

    agent_id = "fundamentals.demand.v1"
    agent_name = "Demand Agent"
    agent_type = AgentType.DEMAND
    version = "0.1.0"

    async def _execute(self, *, balances: list[GasBalanceDaily], is_simulated: bool = True) -> AgentOutcome:
        if not balances:
            return AgentOutcome(
                status=AgentStatus.SKIPPED,
                reasoning_summary="No balance observations available for demand analysis.",
            )

        last7 = balances[-7:]
        prior7 = balances[-14:-7] if len(balances) >= 14 else []
        latest = balances[-1]

        avg_demand_7d = sum(b.demand_total_bcf for b in last7) / len(last7)
        prior_avg = sum(b.demand_total_bcf for b in prior7) / len(prior7) if prior7 else avg_demand_7d
        trend_bcf_d = round(avg_demand_7d - prior_avg, 2)

        outputs = {
            "latest_rescom_demand_bcf": latest.rescom_demand_bcf,
            "latest_industrial_demand_bcf": latest.industrial_demand_bcf,
            "latest_mexico_exports_bcf": latest.mexico_exports_bcf,
            "latest_demand_total_bcf": round(latest.demand_total_bcf, 2),
            "avg_demand_7d_bcf": round(avg_demand_7d, 2),
            "demand_trend_bcf_d": trend_bcf_d,
        }

        classification = DataClassification.SIMULATED if is_simulated else DataClassification.PUBLIC
        source_name = "EIA (seed/simulated)" if is_simulated else "EIA"

        prompt = (
            f"Total Lower-48 demand is averaging {avg_demand_7d:.2f} Bcf/d, a {trend_bcf_d:+.2f} "
            "Bcf/d change vs. the prior week. Summarize in two sentences for a trading desk."
        )
        llm_response = await self.llm.complete([LLMMessage(role="user", content=prompt)])

        direction = "rising" if trend_bcf_d > 0.1 else "falling" if trend_bcf_d < -0.1 else "flat"
        reasoning = (
            f"Total demand is {direction} ({trend_bcf_d:+.2f} Bcf/d week-over-week); latest total "
            f"demand is {latest.demand_total_bcf:.2f} Bcf/d. {llm_response.content}"
        )

        return AgentOutcome(
            outputs=outputs,
            reasoning_summary=reasoning,
            confidence=0.7 if len(balances) >= 14 else 0.5,
            tools=["fundamentals_service.balance"],
            data_sources=[DataSourceRef(provider_id="eia", series_id="EIA.NG.DEMAND", classification=classification)],
            citations=[Citation(source=source_name, reference="natural-gas/cons/sum/data", classification=classification)],
        )
