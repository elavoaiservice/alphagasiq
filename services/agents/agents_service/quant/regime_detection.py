from __future__ import annotations

from agent_sdk import AgentOutcome, BaseAgent, LLMMessage
from quant_service import detect_regime
from schemas import AgentStatus, AgentType, NewsEvent, StorageForecast, WeatherDemandImpact


class RegimeDetectionAgent(BaseAgent):
    """Quantitative Team: classifies the current market regime
    (docs/architecture.md REGIME ENGINE) so the Strategy Team can weight strategies
    accordingly. Entirely deterministic classification (see
    `quant_service.regime.detect_regime`); the LLM call only adds narrative color."""

    agent_id = "quant.regime_detection.v1"
    agent_name = "Regime Detection Agent"
    agent_type = AgentType.REGIME_DETECTION
    version = "0.1.0"

    async def _execute(
        self,
        *,
        recent_returns: list[float],
        weather_impact: WeatherDemandImpact | None = None,
        storage_forecast: StorageForecast | None = None,
        news_events: list[NewsEvent] | None = None,
    ) -> AgentOutcome:
        if not recent_returns:
            return AgentOutcome(status=AgentStatus.SKIPPED, reasoning_summary="No return series available to classify a regime.")

        result = detect_regime(
            recent_returns=recent_returns,
            weather_impact=weather_impact,
            storage_forecast=storage_forecast,
            news_events=news_events,
        )

        prompt = f"Current regime classification: {result.regime.value} ({', '.join(result.drivers)}). One sentence for a trading desk."
        llm_response = await self.llm.complete([LLMMessage(role="user", content=prompt)])
        reasoning = f"Regime: {result.regime.value} — {'; '.join(result.drivers)}. {llm_response.content}"

        return AgentOutcome(
            outputs=result.model_dump(mode="json"),
            reasoning_summary=reasoning,
            confidence=result.confidence,
            tools=["quant_service.regime"],
        )
