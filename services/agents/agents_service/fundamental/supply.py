from __future__ import annotations

from agent_sdk import AgentOutcome, BaseAgent, LLMMessage
from schemas import AgentStatus, AgentType, Citation, DataClassification, DataSourceRef, GasBalanceDaily


class SupplyAgent(BaseAgent):
    """Fundamental Research Team: Lower-48 dry gas production, Canadian imports, LNG
    sendout, and other supply."""

    agent_id = "fundamentals.supply.v1"
    agent_name = "Supply Agent"
    agent_type = AgentType.SUPPLY
    version = "0.1.0"

    async def _execute(self, *, balances: list[GasBalanceDaily], is_simulated: bool = True) -> AgentOutcome:
        if not balances:
            return AgentOutcome(
                status=AgentStatus.SKIPPED,
                reasoning_summary="No balance observations available for supply analysis.",
            )

        last7 = balances[-7:]
        prior7 = balances[-14:-7] if len(balances) >= 14 else []
        latest = balances[-1]

        avg_production_7d = sum(b.production_bcf for b in last7) / len(last7)
        prior_avg = sum(b.production_bcf for b in prior7) / len(prior7) if prior7 else avg_production_7d
        trend_bcf_d = round(avg_production_7d - prior_avg, 2)

        outputs = {
            "latest_production_bcf": latest.production_bcf,
            "latest_canadian_imports_bcf": latest.canadian_imports_bcf,
            "latest_lng_sendout_bcf": latest.lng_sendout_bcf,
            "latest_supply_total_bcf": round(latest.supply_total_bcf, 2),
            "avg_production_7d_bcf": round(avg_production_7d, 2),
            "production_trend_bcf_d": trend_bcf_d,
        }

        classification = DataClassification.SIMULATED if is_simulated else DataClassification.PUBLIC
        source_name = "EIA (seed/simulated)" if is_simulated else "EIA"

        prompt = (
            f"Lower-48 dry gas production is averaging {avg_production_7d:.2f} Bcf/d over the "
            f"last 7 days, a {trend_bcf_d:+.2f} Bcf/d change vs. the prior 7 days. Summarize the "
            "supply picture in two sentences for a trading desk."
        )
        llm_response = await self.llm.complete(
            [LLMMessage(role="user", content=prompt)], system=self.system_instructions
        )

        direction = "growing" if trend_bcf_d > 0.1 else "declining" if trend_bcf_d < -0.1 else "stable"
        reasoning = (
            f"Production is {direction} ({trend_bcf_d:+.2f} Bcf/d week-over-week); latest total "
            f"supply (production + Canadian imports + LNG sendout + other) is "
            f"{latest.supply_total_bcf:.2f} Bcf/d. {llm_response.content}"
        )

        return AgentOutcome(
            outputs=outputs,
            reasoning_summary=reasoning,
            confidence=0.7 if len(balances) >= 14 else 0.5,
            tools=["fundamentals_service.balance"],
            data_sources=[DataSourceRef(provider_id="eia", series_id="EIA.NG.PRODUCTION.DRY", classification=classification)],
            citations=[Citation(source=source_name, reference="natural-gas/prod/sum/data", classification=classification)],
        )
