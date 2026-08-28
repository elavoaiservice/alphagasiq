from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent_sdk import AgentOutcome, BaseAgent, LLMMessage
from schemas import AgentStatus, AgentType, StorageForecast, TradeIdea, WeatherDemandImpact


class DirectionalStrategyAgent(BaseAgent):
    """Strategy Team: proposes an outright directional futures position when the
    Storage and Weather fundamental reads agree on direction. Strategies never submit
    orders — this only ever returns a `TradeIdea` for the AI Investment Committee to
    debate and the Risk Governor to gate.
    """

    agent_id = "strategy.directional.v1"
    agent_name = "Directional Strategy Agent"
    agent_type = AgentType.DIRECTIONAL_STRATEGY
    version = "0.1.0"

    async def _execute(
        self,
        *,
        instrument: str,
        current_price: float,
        storage_forecast: StorageForecast,
        weather_impact: WeatherDemandImpact,
    ) -> AgentOutcome:
        storage_signal = 0
        if storage_forecast.market_consensus_bcf is not None:
            surprise = storage_forecast.forecast_bcf - storage_forecast.market_consensus_bcf
            # Inclusive thresholds (matching quant_service.regime's >= convention): a
            # surprise of exactly +/-2 Bcf is still a meaningful divergence from
            # consensus and must not be silently dropped just because it lands
            # exactly on the boundary — a strict "<"/">" here previously did exactly
            # that on values naturally produced by the synthetic balance generator.
            if surprise <= -2:
                storage_signal = 1  # tighter than expected -> bullish
            elif surprise >= 2:
                storage_signal = -1  # looser than expected -> bearish

        weather_signal = 1 if weather_impact.price_direction == "BULLISH" else (
            -1 if weather_impact.price_direction == "BEARISH" else 0
        )

        combined = storage_signal + weather_signal
        if combined <= 0 and not (storage_signal == 0 and weather_signal > 0):
            return AgentOutcome(
                status=AgentStatus.SKIPPED,
                reasoning_summary=(
                    "Storage and weather signals do not agree on direction "
                    f"(storage_signal={storage_signal}, weather_signal={weather_signal}); "
                    "no directional trade idea proposed."
                ),
            )

        from schemas import Direction, InstrumentType

        direction = Direction.LONG
        target = round(current_price * 1.05, 3)
        stop = round(current_price * 0.97, 3)
        probability = min(0.75, 0.5 + 0.08 * abs(combined))
        confidence = min(0.8, 0.45 + 0.1 * abs(combined) + weather_impact.confidence * 0.1)

        prompt = (
            f"Storage forecast {storage_forecast.forecast_bcf:+.0f} Bcf vs consensus "
            f"{storage_forecast.market_consensus_bcf}; weather implies "
            f"{weather_impact.total_demand_delta_bcf:+.2f} Bcf/d demand change "
            f"({weather_impact.price_direction}). Write a one-sentence trade thesis for a long "
            f"{instrument} position."
        )
        llm_response = await self.llm.complete(
            [LLMMessage(role="user", content=prompt)], system=self.system_instructions
        )
        thesis = llm_response.content if "MOCK LLM" not in llm_response.content else (
            f"Tighter-than-expected storage ({storage_forecast.forecast_bcf:+.0f} Bcf vs consensus) "
            f"combined with a {weather_impact.price_direction.lower()} weather-demand read "
            f"({weather_impact.total_demand_delta_bcf:+.2f} Bcf/d) supports a long {instrument} position."
        )

        trade = TradeIdea(
            strategy="directional_storage_weather_confluence",
            instrument=instrument,
            instrument_type=InstrumentType.FUTURE,
            direction=direction,
            entry=current_price,
            target=target,
            stop_or_invalidation=stop,
            time_horizon="5-10 trading days",
            expected_return=round((target - current_price), 3),
            expected_loss=round((current_price - stop), 3),
            probability_success=probability,
            confidence=confidence,
            thesis=thesis,
            catalysts=[
                f"Storage forecast {storage_forecast.forecast_bcf:+.0f} Bcf vs consensus "
                f"{storage_forecast.market_consensus_bcf}",
                f"{weather_impact.model} weather run implies {weather_impact.total_demand_delta_bcf:+.2f} Bcf/d demand change",
            ],
            risks=[
                "Weather models can reverse on the next run cycle",
                "EIA storage print can surprise vs. both our forecast and consensus",
            ],
            invalidation_conditions=[
                f"Henry Hub {instrument} closes below {stop}",
                "Next weather model run reverses the demand-delta sign",
            ],
            supporting_data=["storage_forecast", "weather_demand_impact"],
            source_citations=["EIA Weekly Storage Report", f"{weather_impact.model} model guidance"],
            expires_at=datetime.now(timezone.utc) + timedelta(days=10),
        )

        return AgentOutcome(
            outputs={"trade_idea": trade.model_dump(mode="json")},
            reasoning_summary=thesis,
            confidence=confidence,
            tools=["strategy.directional.signal_confluence"],
        )
