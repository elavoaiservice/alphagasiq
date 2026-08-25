from __future__ import annotations

from datetime import date, timedelta

from agent_sdk import AgentOutcome, BaseAgent, LLMMessage
from fundamentals_service.storage_forecast import forecast_storage_week, week_ending_for
from schemas import AgentStatus, AgentType, Citation, DataClassification, DataSourceRef, GasBalanceDaily


class StorageAgent(BaseAgent):
    """Fundamental Research Team: EIA storage nowcast/forecast, 5yr average/range, and
    end-of-season projection."""

    agent_id = "fundamentals.storage.v1"
    agent_name = "Storage Agent"
    agent_type = AgentType.STORAGE
    version = "0.1.0"

    async def _execute(
        self,
        *,
        balances: list[GasBalanceDaily],
        five_year_average_bcf: float,
        last_year_bcf: float,
        as_of: date,
        is_simulated: bool = True,
    ) -> AgentOutcome:
        if not balances:
            return AgentOutcome(
                status=AgentStatus.SKIPPED,
                reasoning_summary="No balance observations available for storage forecasting.",
            )

        week_ending = week_ending_for(as_of)
        week_start = week_ending - timedelta(days=6)
        week_balances = [b for b in balances if week_start <= b.flow_date <= week_ending]
        if not week_balances:
            week_balances = balances[-7:]

        forecast = forecast_storage_week(
            week_ending=week_ending,
            daily_balances=week_balances,
            five_year_average_bcf=five_year_average_bcf,
            last_year_bcf=last_year_bcf,
            drivers=["weekly Lower-48 balance derived from Supply/Demand agent inputs"],
        )

        classification = DataClassification.SIMULATED if is_simulated else DataClassification.PUBLIC
        source_name = "EIA Weekly Natural Gas Storage Report (seed/simulated)" if is_simulated else "EIA Weekly Natural Gas Storage Report"

        prompt = (
            f"This week's storage forecast is {forecast.forecast_bcf:+.0f} Bcf, versus a 5-year "
            f"average of {five_year_average_bcf:.0f} Bcf and last year's {last_year_bcf:.0f} Bcf. "
            "Summarize the storage picture in two sentences."
        )
        llm_response = await self.llm.complete([LLMMessage(role="user", content=prompt)])

        reasoning = (
            f"Forecasting a {forecast.forecast_bcf:+.0f} Bcf move for the week ending "
            f"{week_ending.isoformat()} (range {forecast.forecast_range_low:+.0f} to "
            f"{forecast.forecast_range_high:+.0f} Bcf). {llm_response.content}"
        )

        return AgentOutcome(
            outputs=forecast.model_dump(mode="json"),
            reasoning_summary=reasoning,
            confidence=forecast.confidence,
            tools=["fundamentals_service.storage_forecast"],
            data_sources=[DataSourceRef(provider_id="eia", series_id="EIA.NG.STORAGE.LOWER48", classification=classification)],
            citations=[Citation(source=source_name, reference="natural-gas/stor/wkly/data", classification=classification)],
        )
