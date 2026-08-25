from __future__ import annotations

from agent_sdk import AgentOutcome, BaseAgent, LLMMessage
from quant_service import generate_forecast
from quant_service.models import build_model
from schemas import AgentStatus, AgentType, Citation, DataClassification, DataSourceRef, ForecastHorizon, ModelType


class ForecastingAgent(BaseAgent):
    """Quantitative Team: multi-horizon price/return forecasts
    (docs/architecture.md FORECAST ENGINE). Fits the requested model on a
    point-in-time-correct training window and reports the canonical `PriceForecast`
    contract, including which model produced it and its walk-forward-validated
    standing (see `BacktestingAgent`) rather than presenting the forecast as
    infallible.
    """

    agent_id = "quant.forecasting.v1"
    agent_name = "Forecasting Agent"
    agent_type = AgentType.FORECASTING
    version = "0.1.0"

    async def _execute(
        self,
        *,
        instrument: str,
        horizon: ForecastHorizon,
        training_prices: list[float],
        current_price: float,
        model_type: ModelType = ModelType.LINEAR_REGRESSION,
        is_simulated: bool = True,
    ) -> AgentOutcome:
        if len(training_prices) < 2:
            return AgentOutcome(status=AgentStatus.SKIPPED, reasoning_summary="Not enough price history to fit a forecasting model.")

        model = build_model(model_type)
        model.fit(list(range(len(training_prices))), training_prices)
        forecast = generate_forecast(model=model, instrument=instrument, horizon=horizon, current_price=current_price)

        classification = DataClassification.SIMULATED if is_simulated else DataClassification.PUBLIC
        prompt = (
            f"{model_type.value} forecasts {instrument} at {forecast.price_forecast} over {horizon.value} "
            f"({forecast.return_forecast:+.3f} return, {forecast.up_probability:.0%} up-probability). "
            "Summarize in one sentence for a trading desk, noting this is one model's view, not certainty."
        )
        llm_response = await self.llm.complete([LLMMessage(role="user", content=prompt)])
        reasoning = (
            f"{model_type.value} projects {instrument} to {forecast.price_forecast:.3f} over {horizon.value} "
            f"(return {forecast.return_forecast:+.3f}, up-probability {forecast.up_probability:.0%}, "
            f"confidence {forecast.confidence:.0%}). {llm_response.content}"
        )

        return AgentOutcome(
            outputs=forecast.model_dump(mode="json"),
            reasoning_summary=reasoning,
            confidence=forecast.confidence,
            tools=["quant_service.forecast"],
            data_sources=[DataSourceRef(provider_id="mock_cme", series_id="NG.HH.SPOT.DAILY", classification=classification)],
            citations=[Citation(source="quant_service forecasting engine", reference=model_type.value, classification=classification)],
        )
