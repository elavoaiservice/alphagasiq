"""AlphaConsensus(TM)'s forecast extractor (docs/alpha-intelligence.md section 6):
turns already-computed `AgentResult` outputs into the common `AgentForecast` shape.
Pure function -- no DB/LLM/event-bus access. Only extracts a forecast where the
source agent's own single-cycle output already implies a genuine directional read;
never fabricates a direction from a value that doesn't carry one (e.g. LNG/Power/
Pipeline agents report a current level, not a trend, in a single cycle's output, so
they don't contribute a forecast here -- unlike AlphaSignal, which can infer a trend
from its own cycle-over-cycle baseline diff).
"""

from __future__ import annotations

from schemas import AgentForecast, AgentResult, PriceForecast, SignalDirection

_VALID_DIRECTIONS = {d.value for d in SignalDirection}


def _direction_from_delta(delta: float, *, bullish_when_positive: bool) -> SignalDirection:
    if delta == 0:
        return SignalDirection.NEUTRAL
    is_positive = delta > 0
    is_bullish = is_positive if bullish_when_positive else not is_positive
    return SignalDirection.BULLISH if is_bullish else SignalDirection.BEARISH


class ForecastExtractor:
    def extract(
        self,
        *,
        storage_result: AgentResult | None = None,
        weather_result: AgentResult | None = None,
        supply_result: AgentResult | None = None,
        demand_result: AgentResult | None = None,
        forecast_result: AgentResult | None = None,
        relative_value_result: AgentResult | None = None,
        storage_market_consensus_bcf: float | None = None,
    ) -> list[AgentForecast]:
        forecasts: list[AgentForecast] = []

        if storage_result is not None and storage_result.outputs:
            outputs = storage_result.outputs
            forecast_bcf = outputs.get("forecast_bcf")
            # The Storage Agent's own raw AgentResult never carries
            # `market_consensus_bcf` -- that figure is merged in downstream, only for
            # the Directional Strategy Agent's `StorageForecast` input
            # (`chief_trading_agent.py`). The caller (`AppState`) passes the same
            # cycle-level consensus figure through explicitly so this comparison
            # isn't silently unavailable.
            consensus_bcf = outputs.get("market_consensus_bcf")
            if consensus_bcf is None:
                consensus_bcf = storage_market_consensus_bcf
            if forecast_bcf is not None and consensus_bcf is not None:
                # Tighter-than-consensus (a smaller injection or bigger withdrawal
                # than the "street" expects) is bullish.
                direction = _direction_from_delta(consensus_bcf - forecast_bcf, bullish_when_positive=True)
                forecasts.append(
                    AgentForecast(
                        agent_id=storage_result.agent_id,
                        agent_type=storage_result.agent_type,
                        agent_version=storage_result.version,
                        forecast_type="STORAGE_WEEKLY",
                        target="STORAGE_BCF",
                        forecast_value=forecast_bcf,
                        direction=direction,
                        probability=storage_result.confidence or 0.5,
                        confidence=storage_result.confidence or 0.5,
                        drivers=list(outputs.get("drivers", [])),
                        citations=list(storage_result.citations),
                    )
                )

        if weather_result is not None and weather_result.outputs:
            outputs = weather_result.outputs
            price_direction = outputs.get("price_direction")
            if price_direction in _VALID_DIRECTIONS:
                forecasts.append(
                    AgentForecast(
                        agent_id=weather_result.agent_id,
                        agent_type=weather_result.agent_type,
                        agent_version=weather_result.version,
                        forecast_type="WEATHER_DEMAND_IMPACT",
                        target="DEMAND_BCF_D",
                        forecast_value=outputs.get("total_demand_delta_bcf"),
                        direction=SignalDirection(price_direction),
                        probability=weather_result.confidence or 0.5,
                        confidence=weather_result.confidence or 0.5,
                        citations=list(weather_result.citations),
                    )
                )

        if supply_result is not None and supply_result.outputs:
            outputs = supply_result.outputs
            trend = outputs.get("production_trend_bcf_d")
            if trend is not None:
                forecasts.append(
                    AgentForecast(
                        agent_id=supply_result.agent_id,
                        agent_type=supply_result.agent_type,
                        agent_version=supply_result.version,
                        forecast_type="PRODUCTION_TREND",
                        target="PRODUCTION_BCF_D",
                        forecast_value=trend,
                        direction=_direction_from_delta(trend, bullish_when_positive=False),
                        probability=supply_result.confidence or 0.5,
                        confidence=supply_result.confidence or 0.5,
                        citations=list(supply_result.citations),
                    )
                )

        if demand_result is not None and demand_result.outputs:
            outputs = demand_result.outputs
            trend = outputs.get("demand_trend_bcf_d")
            if trend is not None:
                forecasts.append(
                    AgentForecast(
                        agent_id=demand_result.agent_id,
                        agent_type=demand_result.agent_type,
                        agent_version=demand_result.version,
                        forecast_type="DEMAND_TREND",
                        target="DEMAND_BCF_D",
                        forecast_value=trend,
                        direction=_direction_from_delta(trend, bullish_when_positive=True),
                        probability=demand_result.confidence or 0.5,
                        confidence=demand_result.confidence or 0.5,
                        citations=list(demand_result.citations),
                    )
                )

        if forecast_result is not None and forecast_result.outputs.get("price_forecast") is not None:
            pf = PriceForecast.model_validate(forecast_result.outputs)
            direction = (
                SignalDirection.BULLISH
                if pf.up_probability > 0.5
                else SignalDirection.BEARISH
                if pf.up_probability < 0.5
                else SignalDirection.NEUTRAL
            )
            forecasts.append(
                AgentForecast(
                    agent_id=forecast_result.agent_id,
                    agent_type=forecast_result.agent_type,
                    agent_version=forecast_result.version,
                    forecast_type="PRICE_FORECAST",
                    target="PRICE",
                    horizon=pf.horizon.value,
                    forecast_value=pf.price_forecast,
                    direction=direction,
                    probability=pf.up_probability,
                    confidence=pf.confidence,
                    drivers=list(pf.drivers),
                    citations=list(forecast_result.citations),
                )
            )

        if relative_value_result is not None and relative_value_result.outputs.get("direction") is not None:
            outputs = relative_value_result.outputs
            rv_direction = {"CHEAP": SignalDirection.BULLISH, "RICH": SignalDirection.BEARISH}.get(
                outputs["direction"], SignalDirection.NEUTRAL
            )
            forecasts.append(
                AgentForecast(
                    agent_id=relative_value_result.agent_id,
                    agent_type=relative_value_result.agent_type,
                    agent_version=relative_value_result.version,
                    forecast_type="RELATIVE_VALUE",
                    target="RELATIVE_VALUE_MISPRICING",
                    forecast_value=outputs.get("mispricing"),
                    direction=rv_direction,
                    probability=relative_value_result.confidence or 0.5,
                    confidence=relative_value_result.confidence or 0.5,
                    citations=list(relative_value_result.citations),
                )
            )

        return forecasts
