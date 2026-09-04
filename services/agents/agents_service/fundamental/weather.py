from __future__ import annotations

from agent_sdk import AgentOutcome, BaseAgent, LLMMessage
from fundamentals_service.weather_impact import compute_weather_demand_impact
from schemas import AgentType, Citation, DataClassification, DataSourceRef


class WeatherAgent(BaseAgent):
    """Fundamental Research Team: HDD/CDD tracking and model-run delta -> demand
    impact translation (e.g. ECMWF 00z vs 12z, GFS 00z vs 06z)."""

    agent_id = "fundamentals.weather.v1"
    agent_name = "Weather Agent"
    agent_type = AgentType.WEATHER
    version = "0.1.0"

    async def _execute(
        self,
        *,
        model: str,
        run: str,
        comparison_run: str,
        hdd_run: float,
        hdd_comparison: float,
        cdd_run: float,
        cdd_comparison: float,
        is_simulated: bool = True,
    ) -> AgentOutcome:
        impact = compute_weather_demand_impact(
            model=model,
            run=run,
            comparison_run=comparison_run,
            hdd_run=hdd_run,
            hdd_comparison=hdd_comparison,
            cdd_run=cdd_run,
            cdd_comparison=cdd_comparison,
        )

        classification = DataClassification.SIMULATED if is_simulated else DataClassification.PUBLIC
        source_name = "NOAA/NWS + model guidance (seed/simulated)" if is_simulated else "NOAA/NWS"

        prompt = (
            f"{model} run {run} vs {comparison_run}: HDD delta {impact.hdd_delta:+.2f}, CDD delta "
            f"{impact.cdd_delta:+.2f}, implying a {impact.total_demand_delta_bcf:+.2f} Bcf/day total "
            f"demand change ({impact.price_direction}). Summarize in two sentences for a trading desk."
        )
        llm_response = await self.llm.complete(
            [LLMMessage(role="user", content=prompt)], system=self.system_instructions
        )

        reasoning = (
            f"{model} {run} vs {comparison_run} implies a {impact.total_demand_delta_bcf:+.2f} Bcf/d "
            f"total demand change ({impact.price_direction}); res/comm contributes "
            f"{impact.estimated_rescom_delta_bcf:+.2f} Bcf/d and power burn "
            f"{impact.estimated_power_burn_delta_bcf:+.2f} Bcf/d. {llm_response.content}"
        )

        return AgentOutcome(
            outputs=impact.model_dump(mode="json"),
            reasoning_summary=reasoning,
            confidence=impact.confidence,
            tools=["fundamentals_service.weather_impact"],
            data_sources=[DataSourceRef(provider_id="noaa_nws", series_id=f"NOAA.MODEL.{model}", classification=classification)],
            citations=[Citation(source=source_name, reference=f"{model} {run} vs {comparison_run}", classification=classification)],
        )
