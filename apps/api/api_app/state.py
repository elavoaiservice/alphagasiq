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
import logging
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from agent_sdk import build_event_bus, get_default_llm_provider
from agents_service import (
    BacktestingAgent,
    ChiefInvestmentAgent,
    ChiefTradingAgent,
    ForecastingAgent,
    InvestmentCommittee,
    LNGAgent,
    PipelineAgent,
    PowerMarketAgent,
    RegimeDetectionAgent,
    RelativeValueAgent,
)
from alpha_service import (
    AgentAlphaScoreEngine,
    BaselineSnapshot,
    ConsensusEngine,
    ForecastExtractor,
    ImpactEngine,
    MaterialityEngine,
    ScenarioEngine,
    SignalDetector,
)
from config import get_settings
from data_sdk import FetchRequest, ProviderRegistry
from data_service.providers.mock_market_data import MockCMEProvider, MockICEProvider
from data_service.providers.mock_news import MockNewsProvider
from data_service.registry import build_default_registry
from db import SqlAppRepository
from fundamentals_service.lng import LNGTerminalState, compute_netback
from fundamentals_service.pipeline_graph import PipelineGraph, build_default_pipeline_graph
from fundamentals_service.pipeline_graph_neo4j import sync_pipeline_graph_via_neo4j
from fundamentals_service.power_burn import PowerMarketState, estimate_power_burn_bcf_d
from fundamentals_service.seed import (
    generate_daily_balances,
    seed_lng_terminals,
    seed_power_markets,
    seed_storage_baseline,
)
from paper_execution_service import OrderSide, OrderType, PaperExecutionAdapter, PaperOrder, evaluate_post_trade
from quant_service import generate_price_history
from quant_service.metrics import brier_score, directional_accuracy as quant_directional_accuracy
from quant_service.models import build_model as build_quant_model
from risk_service.governor import RiskContext, RiskGovernor
from risk_service.limits import default_risk_limits
from risk_service.metrics import PositionSnapshot, summarize
from schemas import (
    AgentAlphaScore,
    AgentResult,
    AgentType,
    BacktestResult,
    ConsensusView,
    DataClassification,
    DomainEvent,
    EventType,
    ForecastHorizon,
    ImpactAnalysis,
    InvestmentCommitteeDecision,
    ModelType,
    NewsEvent,
    ObservationDraft,
    PostTradeAnalysis,
    PriceForecast,
    RegimeResult,
    RelativeValueSignal,
    RiskCheckResult,
    RiskLimits,
    RiskVerdict,
    ScenarioComparison,
    ScenarioDefinition,
    ScenarioRunResult,
    Signal,
    TimeSeriesObservation,
    TradeIdea,
)

from . import agent_catalog
from .models import Approval, ApprovalActionRecord, ApprovalState, ChatSession

DEFAULT_INSTRUMENT_FALLBACK = "NG-M1"
logger = logging.getLogger(__name__)


class AppState:
    def __init__(self) -> None:
        settings = get_settings()
        self.settings = settings
        self.repo = SqlAppRepository(settings.database_url)
        self.event_bus = build_event_bus(
            impl=settings.event_bus_impl, kafka_bootstrap_servers=settings.kafka_bootstrap_servers
        )
        self.neo4j_driver = None
        if settings.neo4j_uri:
            from neo4j import AsyncGraphDatabase

            auth = (settings.neo4j_user, settings.neo4j_password) if settings.neo4j_password else None
            self.neo4j_driver = AsyncGraphDatabase.driver(settings.neo4j_uri, auth=auth)
        self.providers: ProviderRegistry = build_default_registry()
        llm = get_default_llm_provider()
        self.llm = llm

        self.chief_trading_agent = ChiefTradingAgent(llm=llm)
        self.investment_committee = InvestmentCommittee(llm=llm)
        self.chief_investment_agent = ChiefInvestmentAgent(llm=llm)
        self.pipeline_agent = PipelineAgent(llm=llm)
        self.lng_agent = LNGAgent(llm=llm)
        self.power_market_agent = PowerMarketAgent(llm=llm)
        self.forecasting_agent = ForecastingAgent(llm=llm)
        self.regime_detection_agent = RegimeDetectionAgent(llm=llm)
        self.relative_value_agent = RelativeValueAgent(llm=llm)
        self.backtesting_agent = BacktestingAgent(llm=llm)
        self.risk_governor = RiskGovernor()
        self.alpha_signal_detector = SignalDetector(MaterialityEngine())
        self.alpha_impact_engine = ImpactEngine()
        self.alpha_forecast_extractor = ForecastExtractor()
        self.alpha_score_engine = AgentAlphaScoreEngine()
        self.alpha_consensus_engine = ConsensusEngine()
        self.alpha_scenario_engine = ScenarioEngine()
        # Bounded caches of the most recently detected signals/impact analyses/
        # consensus views, kept in-memory alongside the durable `alpha_signals`/
        # `alpha_impact_analyses`/`alpha_consensus_views` tables so the (synchronous)
        # chat-tool dispatch methods in chat_agent.py can read them the same way
        # every other tool method reads AppState — without making that dispatch path
        # async-aware for just these topics (docs/alpha-intelligence.md Milestone
        # 1-3 provisional decisions).
        self.recent_signals: list[Signal] = []
        self.recent_impacts: list[ImpactAnalysis] = []
        self.recent_consensus_views: list[ConsensusView] = []
        self.recent_scenario_runs: list[ScenarioRunResult] = []

        from .email_service import get_email_provider
        from .rate_limit import SlidingWindowRateLimiter

        self.email_provider = get_email_provider()
        self.magic_link_rate_limiter = SlidingWindowRateLimiter(
            max_requests=settings.magic_link_rate_limit_max_requests,
            window_seconds=settings.magic_link_rate_limit_window_seconds,
        )

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
        # The Quantitative Team's PriceForecast in effect when a trade was submitted —
        # see AppState.submit_trade_idea / close_trade for the unification this enables.
        self.trade_forecasts: dict[UUID, PriceForecast] = {}

        self.agent_execution_log: list[AgentResult] = []

        self.paper_adapter = PaperExecutionAdapter()

        self.chat_sessions: dict[UUID, ChatSession] = {}

        self._seeded = False
        self._lock = asyncio.Lock()

    async def seed(self) -> None:
        async with self._lock:
            if self._seeded:
                return
            await self.repo.init_schema()
            await self.repo.seed_rbac_defaults()
            await self.repo.seed_feature_defaults()
            await self.repo.seed_system_settings_defaults()
            await self.repo.seed_data_feed_configs([p.provider_id for p in self.providers.all()])
            await self.repo.seed_agent_configs(
                [t for t in agent_catalog.IMPLEMENTED_AGENT_TYPES if t != "RISK_GOVERNOR"]
            )
            await self.repo.seed_model_definitions(
                [
                    {
                        "provider": type(self.llm).__name__,
                        "model_name": self.llm.model,
                        "purpose": "Default LLM provider for every agent in this platform.",
                    }
                ]
            )
            await self._seed_initial_agent_versions()
            await self._hydrate_from_repo()
            await self._seed_market_and_fundamentals()
            await self._run_initial_research_cycle()
            self._seeded = True

    async def _seed_initial_agent_versions(self) -> None:
        """Milestone 9: gives every implemented, administrable agent a real `PRODUCTION`
        `AgentVersionRow` snapshot of its actual live configuration at boot, rather than
        starting the versioning system empty. Idempotent -- only runs for an agent_type
        that doesn't already have a `PRODUCTION` version (an admin's own version history
        is never touched). The version's `model_provider`/`model_name` are read straight
        off the agent's real `llm` provider instance, exactly like the Milestone 8
        Control Center does -- never fabricated."""
        for agent_type in agent_catalog.IMPLEMENTED_AGENT_TYPES:
            if agent_type == "RISK_GOVERNOR":
                continue
            if await self.repo.get_production_agent_version(agent_type) is not None:
                continue
            instance = agent_catalog.resolve_agent_instance(self, agent_type)
            if instance is None:
                continue
            draft = await self.repo.create_agent_version(
                agent_type=agent_type,
                version=instance.version,
                model_provider=type(instance.llm).__name__,
                model_name=getattr(instance.llm, "model", None),
                created_by=None,
                notes="Initial production version, snapshotted from the live agent at boot.",
            )
            for next_status in ("TESTING", "APPROVED", "PRODUCTION"):
                draft = await self.repo.transition_agent_version_status(draft["id"], next_status, actor=None)

    async def _hydrate_from_repo(self) -> None:
        """Reloads every durable trading object left over from a previous process
        (`SqlAppRepository` persists to `DATABASE_URL` — sqlite file in dev, real
        Postgres in docker-compose, isolated in-memory sqlite per test). Demo trade
        ideas continuing to accumulate across restarts on top of these is expected:
        `_run_initial_research_cycle` (and `worker.py`'s periodic cycle) always submit
        more trade ideas after this, exactly as they would on a long-running process
        that was never restarted.
        """
        data = await self.repo.hydrate()
        for key, trade in data["trade_ideas"].items():
            self.trade_ideas[UUID(key)] = trade
        for key, forecast in data["forecasts"].items():
            self.trade_forecasts[UUID(key)] = forecast
        for key, decision in data["committee_decisions"].items():
            self.committee_decisions[UUID(key)] = decision
        for key, risk_check in data["risk_checks"].items():
            self.risk_checks[UUID(key)] = risk_check
        for row in data["approvals"]:
            approval = Approval(
                id=UUID(row["id"]),
                trade_id=UUID(row["trade_id"]),
                state=ApprovalState(row["state"]),
                actions=[ApprovalActionRecord.model_validate(a) for a in row["actions"]],
                updated_at=row["updated_at"],
            )
            self.approvals[approval.id] = approval
        for key, entries in data["decision_journal"].items():
            self.decision_journal[UUID(key)] = entries
        for key, analysis in data["post_trade_analyses"].items():
            self.post_trade_analyses[UUID(key)] = analysis
        if data["risk_limits"] is not None:
            self.risk_limits = data["risk_limits"]

    async def persist_approval(self, approval: Approval) -> None:
        """Write-through hook for routers that mutate an `Approval` in place (e.g.
        `POST /approvals/{id}/action`) after looking it up from `state.approvals` —
        the dict already holds the same object by reference, so only the durable copy
        needs updating here. Also the single choke point every approval state
        transition passes through, so it doubles as where TRADE_APPROVED/
        TRADE_REJECTED domain events are published."""
        await self.repo.save_approval(
            approval_id=approval.id,
            trade_id=approval.trade_id,
            state=approval.state.value,
            actions=[a.model_dump(mode="json") for a in approval.actions],
            updated_at=approval.updated_at,
        )
        event_type = {
            # EXECUTED_SIMULATION is included because a normal APPROVE action moves
            # straight from APPROVED_FOR_PAPER_TRADING to EXECUTED_SIMULATION within
            # the same request (routers/approvals.py) before persist_approval() is
            # ever called on it — so the transient APPROVED_FOR_PAPER_TRADING state
            # never reaches here to publish from on its own.
            ApprovalState.APPROVED_FOR_PAPER_TRADING: EventType.TRADE_APPROVED,
            ApprovalState.EXECUTED_SIMULATION: EventType.TRADE_APPROVED,
            ApprovalState.REJECTED: EventType.TRADE_REJECTED,
        }.get(approval.state)
        if event_type is not None:
            await self.event_bus.publish(
                DomainEvent(
                    event_type=event_type,
                    source_service="api.state",
                    payload={"trade_id": str(approval.trade_id), "approval_id": str(approval.id)},
                )
            )

    async def set_risk_limits(self, limits: RiskLimits) -> None:
        self.risk_limits = limits
        await self.repo.save_risk_limits(limits)

    async def _seed_market_and_fundamentals(self) -> None:
        as_of = datetime.now(timezone.utc)
        today = as_of.date()

        self.balances = generate_daily_balances(end_date=today, num_days=120)
        self.storage_baseline = seed_storage_baseline(as_of=today)
        self.lng_terminals = seed_lng_terminals()
        self.power_markets = seed_power_markets()
        self.pipeline_graph = build_default_pipeline_graph()
        if self.neo4j_driver is not None:
            try:
                self.pipeline_graph = await sync_pipeline_graph_via_neo4j(
                    self.neo4j_driver, self.pipeline_graph, database=self.settings.neo4j_database
                )
            except Exception:
                logger.exception(
                    "Neo4j pipeline graph sync failed; falling back to the in-memory graph for this boot"
                )
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
        disabled = await self._disabled_agent_types()

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
            disabled_agent_types=disabled,
        )

        for res in (result.supply, result.demand, result.storage, result.weather, result.strategy, result.chief):
            if res is not None:
                self.agent_execution_log.append(res)

        pipeline_result = None
        if self.pipeline_graph is not None:
            pipeline_result = (
                self.pipeline_agent.skipped_result("Disabled by admin.")
                if "PIPELINE" in disabled
                else await self.pipeline_agent.run(graph=self.pipeline_graph)
            )
            self.agent_execution_log.append(pipeline_result)

        lng_result = (
            self.lng_agent.skipped_result("Disabled by admin.")
            if "LNG" in disabled
            else await self.lng_agent.run(
                terminals=self.lng_terminals,
                henry_hub_price=current_price,
                ttf_price=self.ttf_price[0].value if self.ttf_price else None,
            )
        )
        self.agent_execution_log.append(lng_result)

        power_market_result = (
            self.power_market_agent.skipped_result("Disabled by admin.")
            if "POWER_MARKET" in disabled
            else await self.power_market_agent.run(markets=self.power_markets)
        )
        self.agent_execution_log.append(power_market_result)

        await self._run_alpha_signal_detection(
            research_result=result,
            lng_result=lng_result,
            power_result=power_market_result,
            pipeline_result=pipeline_result,
        )

        await self._run_quant_research(result, disabled_agent_types=disabled, market_consensus_bcf=market_consensus_bcf)

        for trade in result.trade_ideas:
            await self.submit_trade_idea(trade)

    async def _run_quant_research(
        self,
        research_result,
        *,
        disabled_agent_types: frozenset[str] = frozenset(),
        market_consensus_bcf: float | None = None,
    ) -> None:
        """Runs the Quantitative Team over `self.price_history` — a synthetic daily
        Henry Hub spot series generated independently of `self.market_curve` (the
        forward-curve snapshot used for trading). Real desks keep spot and forward
        curves as related but distinct series too; this is not an inconsistency.

        `disabled_agent_types` (docs/agent-governance.md §3) skips a disabled quant
        agent's `_execute()` and records a `SKIPPED` placeholder instead."""
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

        forecast_result = (
            self.forecasting_agent.skipped_result("Disabled by admin.")
            if "FORECASTING" in disabled_agent_types
            else await self.forecasting_agent.run(
                instrument=self.primary_instrument(),
                horizon=ForecastHorizon.SEVEN_DAY,
                training_prices=training_prices,
                current_price=current_price,
            )
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

        regime_result = (
            self.regime_detection_agent.skipped_result("Disabled by admin.")
            if "REGIME_DETECTION" in disabled_agent_types
            else await self.regime_detection_agent.run(
                recent_returns=recent_returns,
                weather_impact=weather_impact,
                storage_forecast=storage_forecast,
                news_events=self.news_events,
            )
        )
        self.agent_execution_log.append(regime_result)
        if regime_result.outputs.get("regime") is not None:
            self.latest_regime = RegimeResult.model_validate(regime_result.outputs)

        rv_result = None
        if self.market_curve and self.ttf_price and "RELATIVE_VALUE" not in disabled_agent_types:
            rv_result = await self.relative_value_agent.run(
                henry_hub_price=self.market_curve[0].value,
                ttf_price=self.ttf_price[0].value,
                m1_price=self.market_curve[0].value,
                m2_price=self.market_curve[1].value if len(self.market_curve) > 1 else self.market_curve[0].value,
            )
            self.agent_execution_log.append(rv_result)
            if rv_result.outputs:
                self.latest_relative_value = rv_result.outputs
        elif self.market_curve and self.ttf_price:
            self.agent_execution_log.append(self.relative_value_agent.skipped_result("Disabled by admin."))

        backtest_result = (
            self.backtesting_agent.skipped_result("Disabled by admin.")
            if "BACKTESTING" in disabled_agent_types
            else await self.backtesting_agent.run(
                instrument=self.primary_instrument(),
                price_history=self.price_history,
                horizon=ForecastHorizon.SEVEN_DAY,
            )
        )
        self.agent_execution_log.append(backtest_result)
        results_by_model = backtest_result.outputs.get("results_by_model")
        if results_by_model:
            self.latest_backtests = {
                name: BacktestResult.model_validate(payload) for name, payload in results_by_model.items()
            }

        await self._run_alpha_consensus(
            research_result=research_result,
            forecast_result=forecast_result,
            rv_result=rv_result,
            market_consensus_bcf=market_consensus_bcf,
        )

    async def _run_alpha_consensus(
        self,
        *,
        research_result,
        forecast_result: AgentResult | None,
        rv_result: AgentResult | None,
        market_consensus_bcf: float | None = None,
    ) -> None:
        """AlphaConsensus(TM)'s integration point (docs/alpha-intelligence.md section
        6): extracts this cycle's `AgentForecast`s, recomputes each contributing
        agent's `AgentAlphaScore`, and computes both a general market-direction
        consensus and (when storage forecasts contributed) a specialized storage-
        forecast-vs-market-consensus view. Only reachable via `_run_quant_research`
        (boot's full cycle) -- `run_chief_trading_cycle`'s lighter on-demand path
        doesn't re-run quant research, so it doesn't reach here either, matching
        that method's already-documented scope."""
        forecasts = self.alpha_forecast_extractor.extract(
            storage_result=research_result.storage,
            weather_result=research_result.weather,
            supply_result=research_result.supply,
            demand_result=research_result.demand,
            forecast_result=forecast_result,
            relative_value_result=rv_result,
            storage_market_consensus_bcf=market_consensus_bcf,
        )
        for forecast in forecasts:
            await self.repo.save_agent_forecast(forecast)
            await self.event_bus.publish(
                DomainEvent(
                    event_type=EventType.AGENT_FORECAST_CREATED,
                    source_service="alpha_service",
                    payload=forecast.model_dump(mode="json"),
                )
            )

        scores: dict[AgentType, AgentAlphaScore] = {}
        for agent_type in {f.agent_type for f in forecasts}:
            recent_results = [r for r in self.agent_execution_log if r.agent_type == agent_type][-20:]
            recent_confidences = [r.confidence for r in recent_results if r.confidence is not None]
            citations_fraction = (
                sum(1.0 for r in recent_results if r.citations) / len(recent_results) if recent_results else None
            )
            score = self.alpha_score_engine.score(
                agent_type,
                recent_confidences=recent_confidences,
                has_citations_fraction=citations_fraction,
                price_forecast=self.latest_forecast if agent_type == AgentType.FORECASTING else None,
                latest_backtests=self.latest_backtests if agent_type == AgentType.FORECASTING else None,
            )
            scores[agent_type] = score
            await self.repo.save_agent_alpha_score(score)

        if not forecasts:
            return

        market_view = self.alpha_consensus_engine.compute(
            consensus_type="MARKET_DIRECTION",
            target="PRICE",
            market=self.primary_instrument(),
            forecasts=forecasts,
            scores=scores,
        )
        if market_view is not None:
            await self._persist_consensus_view(market_view)

        storage_forecasts = [f for f in forecasts if f.target == "STORAGE_BCF"]
        if storage_forecasts:
            storage_outputs = research_result.storage.outputs if research_result.storage is not None else {}
            storage_market_consensus_value = storage_outputs.get("market_consensus_bcf")
            if storage_market_consensus_value is None:
                storage_market_consensus_value = market_consensus_bcf
            storage_view = self.alpha_consensus_engine.compute(
                consensus_type="STORAGE_FORECAST",
                target="STORAGE_BCF",
                market=self.primary_instrument(),
                forecasts=storage_forecasts,
                scores=scores,
                market_consensus_value=storage_market_consensus_value,
            )
            if storage_view is not None:
                await self._persist_consensus_view(storage_view)

    async def _persist_consensus_view(self, view: ConsensusView) -> None:
        await self.repo.save_consensus_view(view)
        self.recent_consensus_views.append(view)
        self.recent_consensus_views = self.recent_consensus_views[-50:]
        event_type = (
            EventType.CONSENSUS_DIVERGENCE_DETECTED if view.dispersion >= 0.5 else EventType.CONSENSUS_UPDATED
        )
        await self.event_bus.publish(
            DomainEvent(event_type=event_type, source_service="alpha_service", payload=view.model_dump(mode="json"))
        )

    def _current_positions(self) -> list[PositionSnapshot]:
        return [
            PositionSnapshot(
                instrument=instrument,
                sector="NATURAL_GAS",
                quantity=pos.quantity,
                price=self.mark_price(instrument),
                avg_price=pos.avg_price,
            )
            for instrument, pos in self.paper_adapter.portfolio.positions.items()
        ]

    async def run_alpha_scenario(
        self,
        definition: ScenarioDefinition,
        *,
        organization_id: str | None = None,
        requested_by: str | None = None,
    ) -> ScenarioRunResult:
        """AlphaScenario(TM)'s integration point (docs/alpha-intelligence.md section
        7): composes `definition` (named base scenarios and/or custom
        `ScenarioVariable`s) into one shock, runs it against the current paper book
        via `alpha_service.scenario_engine.ScenarioEngine`, persists the result, and
        publishes `SCENARIO_RUN`."""
        result = self.alpha_scenario_engine.run(
            definition, self._current_positions(), organization_id=organization_id, requested_by=requested_by
        )
        await self.repo.save_scenario_run(result)
        self.recent_scenario_runs.append(result)
        self.recent_scenario_runs = self.recent_scenario_runs[-50:]
        await self.event_bus.publish(
            DomainEvent(
                event_type=EventType.SCENARIO_RUN, source_service="alpha_service", payload=result.model_dump(mode="json")
            )
        )
        return result

    async def run_alpha_scenario_comparison(
        self,
        *,
        organization_id: str | None = None,
        requested_by: str | None = None,
    ) -> tuple[list[ScenarioRunResult], ScenarioComparison]:
        """Runs every scenario in the standing stress-test library
        (`risk_service.scenarios.SCENARIOS`) against the current paper book in one
        pass and ranks the results -- the "base vs. A vs. B vs. C" comparison from
        docs/alpha-intelligence.md section 7."""
        results, comparison = self.alpha_scenario_engine.run_standing_library(
            self._current_positions(), organization_id=organization_id, requested_by=requested_by
        )
        for result in results:
            await self.repo.save_scenario_run(result)
        self.recent_scenario_runs.extend(results)
        self.recent_scenario_runs = self.recent_scenario_runs[-50:]
        await self.event_bus.publish(
            DomainEvent(
                event_type=EventType.SCENARIO_COMPARISON_RUN,
                source_service="alpha_service",
                payload=comparison.model_dump(mode="json"),
            )
        )
        return results, comparison

    async def run_chief_trading_cycle(self) -> dict:
        """The Chief Trading Agent's on-demand research cycle -- the logic behind both
        `POST /agents/chief-trading/run` and (Milestone 8) `POST /admin/agents/
        CHIEF_TRADING_AGENT/run`. Deliberately lighter than boot's
        `_run_initial_research_cycle` (no pipeline/quant re-run) since this is a manual,
        on-demand trigger of just the fundamentals -> strategy -> committee pipeline."""
        current_price = self.market_curve[0].value if self.market_curve else 3.0
        week_balance = sum(b.balance_bcf for b in self.balances[-7:])
        result = await self.chief_trading_agent.run_research_cycle(
            instrument=self.primary_instrument(),
            current_price=current_price,
            balances=self.balances,
            five_year_average_bcf=self.storage_baseline["five_year_average_bcf"],
            last_year_bcf=self.storage_baseline["year_ago_inventory_bcf"],
            as_of=date.today(),
            weather_kwargs=dict(
                model="GFS", run="latest", comparison_run="previous", hdd_run=2.8, hdd_comparison=2.2, cdd_run=4.0, cdd_comparison=4.5
            ),
            market_consensus_bcf=round(week_balance) + 3,
            disabled_agent_types=await self._disabled_agent_types(),
        )
        for res in (result.supply, result.demand, result.storage, result.weather, result.strategy, result.chief):
            if res is not None:
                self.agent_execution_log.append(res)

        await self._run_alpha_signal_detection(
            research_result=result, lng_result=None, power_result=None, pipeline_result=None
        )

        new_approvals = []
        for trade in result.trade_ideas:
            approval = await self.submit_trade_idea(trade)
            new_approvals.append(approval)

        return {
            "trade_ideas_generated": len(result.trade_ideas),
            "new_approval_ids": [a.id for a in new_approvals],
            "chief_summary": result.chief.reasoning_summary if result.chief else None,
        }

    async def _disabled_agent_types(self) -> frozenset[str]:
        """The real enforcement behind an admin's agent enable/disable/pause action
        (docs/agent-governance.md §3, Milestone 8's `AgentConfigRow`) -- every
        orchestration call site in this module passes this into the composed research
        cycle so a disabled agent's logic genuinely never runs, rather than only
        being recorded as disabled."""
        configs = await self.repo.list_agent_configs()
        return frozenset(c["agent_type"] for c in configs if c["status"] in ("PAUSED", "DISABLED"))

    async def _run_alpha_signal_detection(
        self,
        *,
        research_result,
        lng_result: AgentResult | None,
        power_result: AgentResult | None,
        pipeline_result: AgentResult | None,
    ) -> None:
        """AlphaSignal(TM)'s integration point (docs/alpha-intelligence.md section 2):
        diffs this cycle's already-computed fundamental-agent outputs against the
        previous cycle's stored baselines, persists any signal that clears the
        materiality threshold, and publishes a domain event for it. Called from both
        `_run_initial_research_cycle` and `run_chief_trading_cycle` -- the latter
        doesn't re-run LNG/power/pipeline, so those three arguments are `None` there,
        and the detector simply skips the rules that need them. Immediately runs
        AlphaImpact(TM) (docs/alpha-intelligence.md section 5) against every new signal,
        too -- signal detection and impact analysis are chained at this single
        integration point rather than two separate call sites."""
        raw_baselines = await self.repo.get_signal_baselines()
        baselines = {
            key: BaselineSnapshot(
                key=key, value=b["value"], rolling_window=b["rolling_window"], observed_at=b["observed_at"]
            )
            for key, b in raw_baselines.items()
        }
        signals, updated_baselines = self.alpha_signal_detector.detect(
            research_result=research_result,
            lng_result=lng_result,
            power_result=power_result,
            pipeline_result=pipeline_result,
            market_curve=self.market_curve,
            baselines=baselines,
        )
        await self.repo.save_signal_baselines(
            {
                key: {"value": snap.value, "rolling_window": snap.rolling_window, "observed_at": snap.observed_at}
                for key, snap in updated_baselines.items()
            }
        )
        for sig in signals:
            await self.repo.save_signal(sig)
            self.recent_signals.append(sig)
            await self.event_bus.publish(
                DomainEvent(
                    event_type=EventType.SIGNAL_ESCALATED if sig.materiality_score >= 85 else EventType.SIGNAL_DETECTED,
                    source_service="alpha_service",
                    payload=sig.model_dump(mode="json"),
                )
            )

            analysis = self.alpha_impact_engine.analyze(sig)
            await self.repo.save_impact_analysis(analysis)
            self.recent_impacts.append(analysis)
            await self.event_bus.publish(
                DomainEvent(
                    event_type=EventType.IMPACT_ANALYSIS_CREATED,
                    source_service="alpha_service",
                    payload=analysis.model_dump(mode="json"),
                    lineage_ids=[str(sig.id)],
                )
            )
        if signals:
            self.recent_signals = self.recent_signals[-50:]
            self.recent_impacts = self.recent_impacts[-50:]

    async def submit_trade_idea(self, trade: TradeIdea) -> Approval:
        self.trade_ideas[trade.trade_id] = trade

        # Attach the Quantitative Team's current forecast for this instrument, if any,
        # so that closing this trade can score the forecast against reality too (see
        # close_trade / model_performance_summary). Only meaningful when the forecast
        # is actually for the instrument being traded.
        if self.latest_forecast is not None and self.latest_forecast.instrument == trade.instrument:
            self.trade_forecasts[trade.trade_id] = self.latest_forecast
        await self.repo.save_trade_idea(trade, self.trade_forecasts.get(trade.trade_id))
        await self.event_bus.publish(
            DomainEvent(
                event_type=EventType.TRADE_IDEA_CREATED,
                source_service="api.state",
                payload={
                    "trade_id": str(trade.trade_id),
                    "instrument": trade.instrument,
                    "strategy": trade.strategy,
                    "direction": trade.direction.value,
                },
            )
        )

        disabled = await self._disabled_agent_types()
        decision = await self.investment_committee.deliberate(
            trade=trade,
            supporting_observations=[],
            freshness_limits_seconds={p.provider_id: (p.freshness_sla_seconds or 3600) for p in self.providers.all()},
            existing_positions={
                instrument: pos.quantity for instrument, pos in self.paper_adapter.portfolio.positions.items()
            },
            disabled_agent_types=disabled,
        )
        self.committee_decisions[trade.trade_id] = decision
        await self.repo.save_committee_decision(trade.trade_id, decision)

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
        await self.repo.save_risk_check(trade.trade_id, risk_check)
        if risk_check.verdict != RiskVerdict.ALLOW:
            await self.event_bus.publish(
                DomainEvent(
                    event_type=EventType.RISK_LIMIT_BREACHED,
                    source_service="risk_service.governor",
                    payload={
                        "trade_id": str(trade.trade_id),
                        "verdict": risk_check.verdict.value,
                        "blocking_rule": risk_check.blocking_rule.rule if risk_check.blocking_rule else None,
                    },
                )
            )

        cia_result = (
            self.chief_investment_agent.skipped_result("Disabled by admin.")
            if "CHIEF_INVESTMENT_AGENT" in disabled
            else await self.chief_investment_agent.run(committee_decision=decision, risk_verdict=risk_check.verdict)
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
        await self.persist_approval(approval)

        journal_entry = {
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
        self.decision_journal.setdefault(trade.trade_id, []).append(journal_entry)
        await self.repo.append_decision_journal_entry(trade.trade_id, journal_entry)
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
        await self.event_bus.publish(
            DomainEvent(
                event_type=EventType.POSITION_UPDATED,
                source_service="paper_execution_service",
                payload={
                    "instrument": trade.instrument,
                    "trade_id": str(trade_id),
                    "quantity": self.paper_adapter.portfolio.positions.get(trade.instrument).quantity
                    if trade.instrument in self.paper_adapter.portfolio.positions
                    else 0,
                    "exit_price": exit_fill_price,
                },
            )
        )

        committee = self.committee_decisions[trade_id]
        risk_check = self.risk_checks[trade_id]

        forecast = self.trade_forecasts.get(trade_id)
        forecast_model_type: ModelType | None = None
        forecast_model_version: str | None = None
        if forecast is not None:
            forecast_model_type, forecast_model_version = self._forecast_model_type_and_version(forecast)

        analysis = evaluate_post_trade(
            trade=trade,
            committee=committee,
            risk_check=risk_check,
            entry_price=entry_price,
            exit_price=exit_fill_price,
            opened_at=opened_at,
            closed_at=closed_at,
            forecast=forecast,
            forecast_model_type=forecast_model_type,
            forecast_model_version=forecast_model_version,
        )
        self.post_trade_analyses[trade_id] = analysis
        await self.repo.save_post_trade_analysis(analysis)

        approval.state = ApprovalState.CLOSED
        approval.updated_at = closed_at
        await self.persist_approval(approval)

        journal_entry = {
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
        self.decision_journal.setdefault(trade_id, []).append(journal_entry)
        await self.repo.append_decision_journal_entry(trade_id, journal_entry)

        return {"post_trade_analysis": analysis, "exit_price": exit_fill_price}

    @staticmethod
    def _forecast_model_type_and_version(forecast: PriceForecast) -> tuple[ModelType, str]:
        """Recovers which model actually produced `forecast` and that model's version,
        from its `model_contributions` (the highest-weighted contributor). Looking the
        version up from the live model registry (rather than hardcoding it here) means
        this never drifts from whatever `services/quant` actually ships as that
        model's current version.
        """
        dominant_model_name = max(forecast.model_contributions, key=forecast.model_contributions.get)
        model_type = ModelType(dominant_model_name)
        version = build_quant_model(model_type).version
        return model_type, version

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
        whatever has closed so far) rather than a full statistical framework.

        The `quant` section is where this unifies with `services/quant`: it reports
        the walk-forward-backtested skill of every implemented model
        (`self.latest_backtests`) side by side with each model's *live* skill,
        computed from closed trades that had a `PriceForecast` attached at creation
        time (`self.trade_forecasts`) — using the exact same metric functions
        (`quant_service.metrics.directional_accuracy` / `brier_score`) the backtester
        itself uses, so "how well did this model actually do" and "how well did we
        expect it to do" are directly comparable rather than two disconnected numbers.
        """
        analyses = list(self.post_trade_analyses.values())
        quant_section = self._quant_backtested_vs_live(analyses)

        if not analyses:
            return {
                "closed_trade_count": 0,
                "win_rate": None,
                "avg_thesis_accuracy": None,
                "avg_timing_accuracy": None,
                "avg_risk_accuracy": None,
                "by_quadrant": {},
                "by_strategy": {},
                "quant": quant_section,
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
            "quant": quant_section,
        }

    def _quant_backtested_vs_live(self, analyses: list[PostTradeAnalysis]) -> dict:
        backtested = {
            model_type: {
                "n_folds": result.n_folds,
                "directional_accuracy": result.directional_accuracy,
                "mae": result.mae,
                "rmse": result.rmse,
                "sharpe_ratio": result.sharpe_ratio,
            }
            for model_type, result in self.latest_backtests.items()
        }

        scored = [a for a in analyses if a.quant_model_type is not None and a.quant_predicted_return is not None]
        by_model: dict[str, list[PostTradeAnalysis]] = {}
        for a in scored:
            by_model.setdefault(a.quant_model_type.value, []).append(a)

        def live_stats(group: list[PostTradeAnalysis]) -> dict:
            actual = [g.actual_outcome["actual_return_per_unit"] for g in group]
            predicted = [g.quant_predicted_return for g in group]
            outcomes = [a_val > 0 for a_val in actual]
            probabilities = [g.quant_up_probability for g in group if g.quant_up_probability is not None]
            return {
                "n": len(group),
                "directional_accuracy": round(quant_directional_accuracy(actual, predicted), 4),
                "brier_score": round(brier_score(probabilities, outcomes), 4) if probabilities else None,
            }

        return {
            "backtested": backtested,
            "live": {
                "n_forecasts_resolved": len(scored),
                "directional_accuracy": round(quant_directional_accuracy(
                    [a.actual_outcome["actual_return_per_unit"] for a in scored],
                    [a.quant_predicted_return for a in scored],
                ), 4) if scored else None,
                "brier_score": round(brier_score(
                    [a.quant_up_probability for a in scored if a.quant_up_probability is not None],
                    [a.actual_outcome["actual_return_per_unit"] > 0 for a in scored if a.quant_up_probability is not None],
                ), 4) if any(a.quant_up_probability is not None for a in scored) else None,
                "by_model": {model_type: live_stats(group) for model_type, group in by_model.items()},
            },
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

    from .email_service import reset_console_email_provider

    reset_console_email_provider()
