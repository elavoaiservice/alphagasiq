"""In-memory application state for the MVP.

This is the Milestone 1-2 persistence layer: it lets the whole platform boot and be
fully exercised with `docker compose up` / `uvicorn` and zero external dependencies
(no Postgres connection required to demo the API). `infrastructure/db/migrations`
defines the production Postgres/TimescaleDB schema this state mirrors; swapping this
module for a SQLAlchemy-backed repository is the next milestone's wiring and does not
require changing any router.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from agent_sdk import InMemoryEventBus, get_default_llm_provider
from agents_service import (
    BacktestingAgent,
    ChiefInvestmentAgent,
    ChiefTradingAgent,
    ForecastingAgent,
    InvestmentCommittee,
    PipelineAgent,
    RegimeDetectionAgent,
    RelativeValueAgent,
)
from config import get_settings
from data_sdk import FetchRequest, ProviderRegistry
from data_service.providers.mock_market_data import MockCMEProvider, MockICEProvider
from data_service.providers.mock_news import MockNewsProvider
from data_service.registry import build_default_registry
from fundamentals_service.lng import LNGTerminalState, compute_netback
from fundamentals_service.pipeline_graph import PipelineGraph, build_default_pipeline_graph
from fundamentals_service.power_burn import PowerMarketState, estimate_power_burn_bcf_d
from fundamentals_service.seed import (
    generate_daily_balances,
    seed_lng_terminals,
    seed_power_markets,
    seed_storage_baseline,
)
from paper_execution_service import OrderSide, OrderType, PaperExecutionAdapter, PaperOrder, evaluate_post_trade
from quant_service import generate_price_history
from risk_service.governor import RiskContext, RiskGovernor
from risk_service.limits import default_risk_limits
from risk_service.metrics import PositionSnapshot, summarize
from schemas import (
    AgentResult,
    BacktestResult,
    DataClassification,
    ForecastHorizon,
    InvestmentCommitteeDecision,
    NewsEvent,
    ObservationDraft,
    PostTradeAnalysis,
    PriceForecast,
    RegimeResult,
    RelativeValueSignal,
    RiskCheckResult,
    RiskLimits,
    RiskVerdict,
    TimeSeriesObservation,
    TradeIdea,
)

from .models import Approval, ApprovalState, ChatSession

DEFAULT_INSTRUMENT_FALLBACK = "NG-M1"


class AppState:
    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.event_bus = InMemoryEventBus()
        self.providers: ProviderRegistry = build_default_registry()
        llm = get_default_llm_provider()

        self.chief_trading_agent = ChiefTradingAgent(llm=llm)
        self.investment_committee = InvestmentCommittee(llm=llm)
        self.chief_investment_agent = ChiefInvestmentAgent(llm=llm)
        self.pipeline_agent = PipelineAgent(llm=llm)
        self.forecasting_agent = ForecastingAgent(llm=llm)
        self.regime_detection_agent = RegimeDetectionAgent(llm=llm)
        self.relative_value_agent = RelativeValueAgent(llm=llm)
        self.backtesting_agent = BacktestingAgent(llm=llm)
        self.risk_governor = RiskGovernor()

        self.risk_limits: RiskLimits = default_risk_limits()
        self.trading_halted: bool = False
        self.current_daily_loss: float = 0.0
        self.current_drawdown: float = 0.0

        self.balances = []
        self.storage_baseline: dict[str, float] = {}
        self.market_curve: list[ObservationDraft] = []
        self.ttf_price: list[ObservationDraft] = []
        self.news_events: list[NewsEvent] = []
        self.lng_terminals: list[LNGTerminalState] = []
        self.power_markets: list[PowerMarketState] = []
        self.pipeline_graph: PipelineGraph | None = None
        self.price_history: list[TimeSeriesObservation] = []
        self.latest_forecast: PriceForecast | None = None
        self.latest_regime: RegimeResult | None = None
        self.latest_relative_value: dict | None = None
        self.latest_backtests: dict[str, BacktestResult] = {}

        self.trade_ideas: dict[UUID, TradeIdea] = {}
        self.committee_decisions: dict[UUID, InvestmentCommitteeDecision] = {}
        self.risk_checks: dict[UUID, RiskCheckResult] = {}
        self.approvals: dict[UUID, Approval] = {}
        self.decision_journal: dict[UUID, list[dict]] = {}  # trade_id -> append-only entries
        self.post_trade_analyses: dict[UUID, PostTradeAnalysis] = {}

        self.agent_execution_log: list[AgentResult] = []

        self.paper_adapter = PaperExecutionAdapter()

        self.chat_sessions: dict[UUID, ChatSession] = {}

        self._seeded = False
        self._lock = asyncio.Lock()

    async def seed(self) -> None:
        async with self._lock:
            if self._seeded:
                return
            await self._seed_market_and_fundamentals()
            await self._run_initial_research_cycle()
            self._seeded = True

    async def _seed_market_and_fundamentals(self) -> None:
        as_of = datetime.now(timezone.utc)
        today = as_of.date()

        self.balances = generate_daily_balances(end_date=today, num_days=120)
        self.storage_baseline = seed_storage_baseline(as_of=today)
        self.lng_terminals = seed_lng_terminals()
        self.power_markets = seed_power_markets()
        self.pipeline_graph = build_default_pipeline_graph()
        self.price_history = generate_price_history(end_date=today, num_days=250)

        cme = self.providers.get("mock_cme")
        self.market_curve = await cme.fetch(FetchRequest(end=as_of))

        ice = self.providers.get("mock_ice")
        self.ttf_price = await ice.fetch(FetchRequest(end=as_of))

        news_provider = self.providers.get("mock_news")
        news_observations = await news_provider.fetch(FetchRequest(end=as_of))
        self.news_events = _observations_to_news_events(news_observations)

    def primary_instrument(self) -> str:
        """The tradable instrument for strategy/research purposes: always the actual
        current front-month (M1) contract symbol, so a generated `TradeIdea.entry`
        matches the real executable price for that symbol (`mark_price()` looks up by
        symbol, and M1 rolls month-to-month like any real futures desk's front
        month). A previous version hardcoded a fixed contract month here, which
        silently desynced the recorded entry price from the price paper orders
        actually executed at — fixed after the Milestone 11 close-trade flow surfaced
        the mismatch.
        """
        return self.market_curve[0].symbol if self.market_curve else DEFAULT_INSTRUMENT_FALLBACK

    async def _run_initial_research_cycle(self) -> None:
        today = date.today()
        current_price = self.market_curve[0].value if self.market_curve else 3.0
        week_balance = sum(b.balance_bcf for b in self.balances[-7:])
        market_consensus_bcf = round(week_balance) + 3  # illustrative "street" estimate

        result = await self.chief_trading_agent.run_research_cycle(
            instrument=self.primary_instrument(),
            current_price=current_price,
            balances=self.balances,
            five_year_average_bcf=self.storage_baseline["five_year_average_bcf"],
            last_year_bcf=self.storage_baseline["year_ago_inventory_bcf"],
            as_of=today,
            weather_kwargs=dict(
                model="ECMWF",
                run=(datetime.now(timezone.utc)).strftime("%Y-%m-%dT00Z"),
                comparison_run=(datetime.now(timezone.utc) - timedelta(hours=12)).strftime("%Y-%m-%dT12Z"),
                hdd_run=3.2,
                hdd_comparison=1.4,
                cdd_run=5.0,
                cdd_comparison=6.5,
            ),
            market_consensus_bcf=market_consensus_bcf,
        )

        for res in (result.supply, result.demand, result.storage, result.weather, result.strategy, result.chief):
            if res is not None:
                self.agent_execution_log.append(res)

        if self.pipeline_graph is not None:
            pipeline_result = await self.pipeline_agent.run(graph=self.pipeline_graph)
            self.agent_execution_log.append(pipeline_result)

        await self._run_quant_research(result)

        for trade in result.trade_ideas:
            await self.submit_trade_idea(trade)

    async def _run_quant_research(self, research_result) -> None:
        """Runs the Quantitative Team over `self.price_history` — a synthetic daily
        Henry Hub spot series generated independently of `self.market_curve` (the
        forward-curve snapshot used for trading). Real desks keep spot and forward
        curves as related but distinct series too; this is not an inconsistency."""
        if len(self.price_history) < 60:
            return

        sorted_history = sorted(self.price_history, key=lambda o: o.observation_time)
        prices = [o.value for o in sorted_history]
        training_prices = prices[-60:]
        current_price = prices[-1]
        recent_returns = [
            (training_prices[i] - training_prices[i - 1]) / training_prices[i - 1]
            for i in range(1, len(training_prices))
            if training_prices[i - 1] != 0
        ]

        forecast_result = await self.forecasting_agent.run(
            instrument=self.primary_instrument(),
            horizon=ForecastHorizon.SEVEN_DAY,
            training_prices=training_prices,
            current_price=current_price,
        )
        self.agent_execution_log.append(forecast_result)
        if forecast_result.outputs.get("price_forecast") is not None:
            self.latest_forecast = PriceForecast.model_validate(forecast_result.outputs)

        weather_impact = None
        if research_result.weather is not None and research_result.weather.outputs:
            from schemas import WeatherDemandImpact

            weather_impact = WeatherDemandImpact.model_validate(research_result.weather.outputs)
        storage_forecast = None
        if research_result.storage is not None and research_result.storage.outputs:
            from schemas import StorageForecast

            storage_forecast = StorageForecast.model_validate(research_result.storage.outputs)

        regime_result = await self.regime_detection_agent.run(
            recent_returns=recent_returns,
            weather_impact=weather_impact,
            storage_forecast=storage_forecast,
            news_events=self.news_events,
        )
        self.agent_execution_log.append(regime_result)
        if regime_result.outputs.get("regime") is not None:
            self.latest_regime = RegimeResult.model_validate(regime_result.outputs)

        if self.market_curve and self.ttf_price:
            rv_result = await self.relative_value_agent.run(
                henry_hub_price=self.market_curve[0].value,
                ttf_price=self.ttf_price[0].value,
                m1_price=self.market_curve[0].value,
                m2_price=self.market_curve[1].value if len(self.market_curve) > 1 else self.market_curve[0].value,
            )
            self.agent_execution_log.append(rv_result)
            if rv_result.outputs:
                self.latest_relative_value = rv_result.outputs

        backtest_result = await self.backtesting_agent.run(
            instrument=self.primary_instrument(),
            price_history=self.price_history,
            horizon=ForecastHorizon.SEVEN_DAY,
        )
        self.agent_execution_log.append(backtest_result)
        results_by_model = backtest_result.outputs.get("results_by_model")
        if results_by_model:
            self.latest_backtests = {
                name: BacktestResult.model_validate(payload) for name, payload in results_by_model.items()
            }

    async def submit_trade_idea(self, trade: TradeIdea) -> Approval:
        self.trade_ideas[trade.trade_id] = trade

        decision = await self.investment_committee.deliberate(
            trade=trade,
            supporting_observations=[],
            freshness_limits_seconds={p.provider_id: (p.freshness_sla_seconds or 3600) for p in self.providers.all()},
            existing_positions={
                instrument: pos.quantity for instrument, pos in self.paper_adapter.portfolio.positions.items()
            },
        )
        self.committee_decisions[trade.trade_id] = decision

        ctx = RiskContext(
            trade=trade,
            limits=self.risk_limits,
            proposed_position_size=100,
            current_daily_loss=self.current_daily_loss,
            current_drawdown=self.current_drawdown,
            trading_halted=self.trading_halted,
            trade_confidence=trade.confidence,
            model_version=self.chief_trading_agent.version,
            approved_model_versions=frozenset({self.chief_trading_agent.version}),
        )
        risk_check = self.risk_governor.evaluate_fail_closed(ctx)
        self.risk_checks[trade.trade_id] = risk_check

        cia_result = await self.chief_investment_agent.run(
            committee_decision=decision, risk_verdict=risk_check.verdict
        )
        self.agent_execution_log.append(cia_result)

        approval = Approval(trade_id=trade.trade_id)
        if risk_check.verdict != RiskVerdict.ALLOW:
            approval.state = ApprovalState.RISK_REVIEW
        elif cia_result.outputs.get("forward_for_human_review"):
            approval.state = ApprovalState.HUMAN_REVIEW
        else:
            approval.state = ApprovalState.REJECTED
        self.approvals[approval.id] = approval

        self.decision_journal.setdefault(trade.trade_id, []).append(
            {
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "thesis": trade.thesis,
                "counter_thesis": decision.bear_case,
                "model_versions": {"chief_trading_agent": self.chief_trading_agent.version},
                "agent_versions": {
                    "storage_agent": self.chief_trading_agent.storage_agent.version,
                    "weather_agent": self.chief_trading_agent.weather_agent.version,
                },
                "risk_analysis": {"verdict": risk_check.verdict.value, "governor_version": risk_check.governor_version},
                "human_decision": None,
                "paper_execution": None,
                "outcome": None,
            }
        )
        return approval

    async def close_trade(
        self, trade_id: UUID, *, exit_price: float | None = None, exit_reason: str = "manual_close"
    ) -> dict:
        """Flattens the paper position tied to `trade_id`, then generates the
        `PostTradeAnalysis` (docs/architecture.md "POST-TRADE ANALYSIS") comparing
        expected vs. actual outcome. Only valid for a trade that actually reached
        `EXECUTED_SIMULATION` — you cannot "close" a position that was never opened.
        """
        trade = self.trade_ideas[trade_id]
        approval = next((a for a in self.approvals.values() if a.trade_id == trade_id), None)
        if approval is None:
            raise ValueError("No approval record for this trade_id")
        if approval.state != ApprovalState.EXECUTED_SIMULATION:
            raise ValueError(
                f"Trade is in state {approval.state.value}, not EXECUTED_SIMULATION; nothing to close"
            )

        position = self.paper_adapter.portfolio.positions.get(trade.instrument)
        if position is None or position.quantity == 0:
            raise ValueError("No open paper position for this trade's instrument")

        entry_price = position.avg_price
        opened_at = trade.created_at

        close_side = OrderSide.SELL if position.quantity > 0 else OrderSide.BUY
        close_order = PaperOrder(
            trade_id=trade_id,
            instrument=trade.instrument,
            order_type=OrderType.MARKET,
            side=close_side,
            quantity=abs(position.quantity),
        )
        market_price = exit_price if exit_price is not None else self.mark_price(trade.instrument)
        fills = await self.paper_adapter.submit_order(close_order, market_price)
        exit_fill_price = fills[0].fill_price if fills else market_price
        closed_at = datetime.now(timezone.utc)

        committee = self.committee_decisions[trade_id]
        risk_check = self.risk_checks[trade_id]
        analysis = evaluate_post_trade(
            trade=trade,
            committee=committee,
            risk_check=risk_check,
            entry_price=entry_price,
            exit_price=exit_fill_price,
            opened_at=opened_at,
            closed_at=closed_at,
        )
        self.post_trade_analyses[trade_id] = analysis

        approval.state = ApprovalState.CLOSED
        approval.updated_at = closed_at

        self.decision_journal.setdefault(trade_id, []).append(
            {
                "recorded_at": closed_at.isoformat(),
                "thesis": trade.thesis,
                "counter_thesis": committee.bear_case,
                "model_versions": {"chief_trading_agent": self.chief_trading_agent.version},
                "agent_versions": {},
                "risk_analysis": {"verdict": risk_check.verdict.value, "governor_version": risk_check.governor_version},
                "human_decision": {"action": "CLOSE_POSITION", "reason": exit_reason},
                "paper_execution": {"exit_price": exit_fill_price, "instrument": trade.instrument},
                "outcome": analysis.model_dump(mode="json"),
            }
        )

        return {"post_trade_analysis": analysis, "exit_price": exit_fill_price}

    def portfolio_risk_summary(self):
        positions = [
            PositionSnapshot(
                instrument=instrument,
                sector="NATURAL_GAS",
                quantity=pos.quantity,
                price=self.mark_price(instrument),
                avg_price=pos.avg_price,
            )
            for instrument, pos in self.paper_adapter.portfolio.positions.items()
        ]
        equity_curve = [100_000, 100_500, 99_800, 101_200, 100_900]
        return summarize(positions, equity_curve)

    def model_performance_summary(self) -> dict:
        """Aggregates closed-trade outcomes by strategy — the Milestone 11
        "model-performance dashboard." Deliberately simple (counts + averages over
        whatever has closed so far) rather than a walk-forward statistical framework;
        that belongs to the Quantitative Team's backtesting engine (`services/quant`,
        not yet built) once there is enough closed-trade history to make it
        meaningful.
        """
        analyses = list(self.post_trade_analyses.values())
        if not analyses:
            return {
                "closed_trade_count": 0,
                "win_rate": None,
                "avg_thesis_accuracy": None,
                "avg_timing_accuracy": None,
                "avg_risk_accuracy": None,
                "by_quadrant": {},
                "by_strategy": {},
            }

        def avg(values: list[float]) -> float:
            return round(sum(values) / len(values), 3)

        wins = sum(1 for a in analyses if (a.actual_outcome.get("actual_return_per_unit") or 0) > 0)
        by_quadrant: dict[str, int] = {}
        for a in analyses:
            by_quadrant[a.quadrant.value] = by_quadrant.get(a.quadrant.value, 0) + 1

        by_strategy: dict[str, dict] = {}
        for a in analyses:
            trade = self.trade_ideas.get(a.trade_id)
            strategy = trade.strategy if trade else "unknown"
            bucket = by_strategy.setdefault(strategy, {"count": 0, "thesis_accuracies": [], "wins": 0})
            bucket["count"] += 1
            bucket["thesis_accuracies"].append(a.thesis_accuracy)
            if (a.actual_outcome.get("actual_return_per_unit") or 0) > 0:
                bucket["wins"] += 1
        for strategy, bucket in by_strategy.items():
            bucket["avg_thesis_accuracy"] = avg(bucket.pop("thesis_accuracies"))
            bucket["win_rate"] = round(bucket["wins"] / bucket["count"], 3)

        return {
            "closed_trade_count": len(analyses),
            "win_rate": round(wins / len(analyses), 3),
            "avg_thesis_accuracy": avg([a.thesis_accuracy for a in analyses]),
            "avg_timing_accuracy": avg([a.timing_accuracy for a in analyses]),
            "avg_risk_accuracy": avg([a.risk_accuracy for a in analyses]),
            "by_quadrant": by_quadrant,
            "by_strategy": by_strategy,
        }

    def mark_price(self, instrument: str) -> float:
        for obs in self.market_curve:
            if obs.symbol == instrument:
                return obs.value
        return self.market_curve[0].value if self.market_curve else 3.0


def _observations_to_news_events(observations: list[ObservationDraft]) -> list[NewsEvent]:
    events: list[NewsEvent] = []
    for obs in observations:
        magnitude = float(obs.value)
        bullish_bearish = obs.metadata.get("bullish_bearish", "NEUTRAL")
        events.append(
            NewsEvent(
                headline=obs.metadata.get("headline", ""),
                source=obs.source,
                source_url=obs.metadata.get("source_url", ""),
                published_at=obs.publication_time,
                event_type=obs.sub_category or "other",
                locations=obs.metadata.get("locations", [obs.geography] if obs.geography else []),
                summary=obs.metadata.get("headline", ""),
                supply_impact_bcf_day=round(-magnitude * 2 if bullish_bearish == "BULLISH" else magnitude * 2 if bullish_bearish == "BEARISH" else 0.0, 2),
                affected_markets=["Henry Hub"],
                bullish_bearish=bullish_bearish,
                magnitude=magnitude,
                confidence=0.6,
                citations=[obs.metadata.get("source_url", obs.source)],
            )
        )
    return events


_state: AppState | None = None


async def get_app_state() -> AppState:
    global _state
    if _state is None:
        _state = AppState()
        await _state.seed()
    return _state


def reset_app_state() -> None:
    """Test-only hook."""
    global _state
    _state = None
