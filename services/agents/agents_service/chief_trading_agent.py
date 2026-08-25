from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from agent_sdk import AgentOutcome, BaseAgent, LLMProvider
from schemas import AgentResult, AgentType, GasBalanceDaily, StorageForecast, TradeIdea, WeatherDemandImpact

from .fundamental.demand import DemandAgent
from .fundamental.storage import StorageAgent
from .fundamental.supply import SupplyAgent
from .fundamental.weather import WeatherAgent
from .strategy.directional import DirectionalStrategyAgent


@dataclass
class ResearchCycleResult:
    """Everything a single Chief Trading Agent research cycle produced, with every
    sub-agent's full `AgentResult` preserved for the audit trail (docs/agents.md)."""

    supply: AgentResult
    demand: AgentResult
    storage: AgentResult
    weather: AgentResult
    strategy: AgentResult
    trade_ideas: list[TradeIdea] = field(default_factory=list)
    chief: AgentResult | None = None


class ChiefTradingAgent(BaseAgent):
    """Orchestrates the Fundamental Research Team and the Strategy Team for a single
    instrument, then hands any resulting `TradeIdea`(s) onward. Does not itself decide
    whether a trade proceeds — that's the AI Investment Committee's job, subject
    unconditionally to the Risk Governor (see docs/risk-framework.md).
    """

    agent_id = "executive.chief_trading_agent.v1"
    agent_name = "Chief Trading Agent"
    agent_type = AgentType.CHIEF_TRADING_AGENT
    version = "0.1.0"

    def __init__(self, llm: LLMProvider | None = None):
        super().__init__(llm=llm)
        self.supply_agent = SupplyAgent(llm=llm)
        self.demand_agent = DemandAgent(llm=llm)
        self.storage_agent = StorageAgent(llm=llm)
        self.weather_agent = WeatherAgent(llm=llm)
        self.strategy_agent = DirectionalStrategyAgent(llm=llm)

    async def run_research_cycle(
        self,
        *,
        instrument: str,
        current_price: float,
        balances: list[GasBalanceDaily],
        five_year_average_bcf: float,
        last_year_bcf: float,
        as_of: date,
        weather_kwargs: dict,
        market_consensus_bcf: float | None = None,
        is_simulated: bool = True,
    ) -> ResearchCycleResult:
        supply_result = await self.supply_agent.run(balances=balances, is_simulated=is_simulated)
        demand_result = await self.demand_agent.run(balances=balances, is_simulated=is_simulated)
        storage_result = await self.storage_agent.run(
            balances=balances,
            five_year_average_bcf=five_year_average_bcf,
            last_year_bcf=last_year_bcf,
            as_of=as_of,
            is_simulated=is_simulated,
        )
        weather_result = await self.weather_agent.run(is_simulated=is_simulated, **weather_kwargs)

        trade_ideas: list[TradeIdea] = []
        strategy_result = None
        if storage_result.outputs and weather_result.outputs:
            storage_forecast = StorageForecast.model_validate(
                {**storage_result.outputs, "market_consensus_bcf": market_consensus_bcf}
            )
            weather_impact = WeatherDemandImpact.model_validate(weather_result.outputs)
            strategy_result = await self.strategy_agent.run(
                instrument=instrument,
                current_price=current_price,
                storage_forecast=storage_forecast,
                weather_impact=weather_impact,
            )
            if strategy_result.outputs.get("trade_idea"):
                trade_ideas.append(TradeIdea.model_validate(strategy_result.outputs["trade_idea"]))

        chief_result = await self.run(
            instrument=instrument,
            trade_idea_count=len(trade_ideas),
            supply_confidence=supply_result.confidence,
            demand_confidence=demand_result.confidence,
        )

        return ResearchCycleResult(
            supply=supply_result,
            demand=demand_result,
            storage=storage_result,
            weather=weather_result,
            strategy=strategy_result,
            trade_ideas=trade_ideas,
            chief=chief_result,
        )

    async def _execute(
        self,
        *,
        instrument: str,
        trade_idea_count: int,
        supply_confidence: float | None,
        demand_confidence: float | None,
    ) -> AgentOutcome:
        summary = (
            f"Completed a research cycle for {instrument}: fundamental research team consulted "
            f"(supply confidence {supply_confidence}, demand confidence {demand_confidence}); "
            f"{trade_idea_count} trade idea(s) generated for AI Investment Committee review."
        )
        return AgentOutcome(
            outputs={"instrument": instrument, "trade_idea_count": trade_idea_count},
            reasoning_summary=summary,
            confidence=0.7,
            tools=["chief_trading_agent.orchestrate"],
        )
