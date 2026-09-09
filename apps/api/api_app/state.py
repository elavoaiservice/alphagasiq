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
from typing import Any
from uuid import UUID

from agent_sdk import build_event_bus, build_llm_provider, get_default_llm_provider
from agents_service import (
    BacktestingAgent,
    ChiefInvestmentAgent,
    ChiefTradingAgent,
    ForecastingAgent,
    InvestmentCommittee,
    LNGAgent,
    NewsIntelligenceAgent,
    PipelineAgent,
    PowerMarketAgent,
    RegimeDetectionAgent,
    RelativeValueAgent,
    ResearchCycleResult,
)
from alpha_service import (
    AgentAlphaScoreEngine,
    AlphaCorroborationEngine,
    BaselineSnapshot,
    BriefEngine,
    ConsensusEngine,
    ForecastExtractor,
    ImpactEngine,
    LessonEngine,
    MaterialityEngine,
    MemoryBuilder,
    ReplayEngine,
    ScenarioEngine,
    SignalDetector,
    compute_market_bias,
)
from config import get_settings
from data_sdk import FetchRequest, ProviderRegistry
from data_service.providers.eia import EIA_SERIES_MAP
from data_service.providers.mock_market_data import MockCMEProvider, MockICEProvider
from data_service.providers.mock_news import MockNewsProvider
from data_service.quality import DataQualityService
from data_service.registry import build_default_registry
from db import SqlAppRepository
from enterprise_data_service import (
    EnterpriseCorroborationEngine,
    EnterpriseOpportunityEngine,
    EnterprisePosition,
    ModelRoutingEngine,
    RetentionEngine,
    agent_is_entitled,
)
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
    AsOfReplayResult,
    BacktestResult,
    ConsensusView,
    DataClassification,
    DomainEvent,
    EnterpriseDataClassification,
    EnterpriseDataDomain,
    EnterpriseDataEntitlement,
    EnterpriseOpportunity,
    EnterpriseOpportunityType,
    EventType,
    ForecastHorizon,
    ImpactAnalysis,
    IntelligenceBrief,
    InvestmentCommitteeDecision,
    LessonProposal,
    MarketBiasResult,
    MemoryRecord,
    ModelType,
    NewsEvent,
    ObservationDraft,
    PostTradeAnalysis,
    PriceForecast,
    RegimeResult,
    RelativeValueSignal,
    RetentionPolicy,
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


def _derive_storage_baseline(storage_drafts: list[ObservationDraft]) -> dict[str, float] | None:
    """Computes every `storage_baseline` field directly from EIA's real weekly
    storage history -- no interpolation, no synthetic blending. `None` when there
    isn't enough real history to compute a meaningful baseline (fewer than 2 weekly
    observations), so the caller leaves the existing baseline untouched rather than
    overwrite it with a partial, misleading figure."""
    if len(storage_drafts) < 2:
        return None
    ordered = sorted(storage_drafts, key=lambda d: d.observation_time)
    current = ordered[-1]
    values = [d.value for d in ordered]
    year_ago_target = current.observation_time - timedelta(weeks=52)
    year_ago = min(ordered, key=lambda d: abs((d.observation_time - year_ago_target).total_seconds()))
    return {
        "current_inventory_bcf": current.value,
        "year_ago_inventory_bcf": year_ago.value,
        "five_year_average_bcf": sum(values) / len(values),
        "five_year_low_bcf": min(values),
        "five_year_high_bcf": max(values),
    }


def _derive_weather_kwargs(weather_drafts: list[ObservationDraft], *, previous: dict) -> dict | None:
    """Builds `ChiefTradingAgent.run_research_cycle()`'s `weather_kwargs` from
    NOAA's real national HDD/CDD approximation (`noaa.py::_national_degree_day_average`),
    diffed against the previous call's snapshot for the delta `WeatherAgent`/
    AlphaSignal expect. `None` when this fetch produced no national HDD/CDD draft
    (e.g. every per-region forecast fetch failed) -- the caller leaves
    `weather_kwargs` untouched rather than overwrite real data with a partial
    result."""
    national = next(
        (d for d in weather_drafts if d.series_id == "NOAA.HDD_CDD.NATIONAL_APPROXIMATION"), None
    )
    if national is None:
        return None
    hdd_run = national.metadata["hdd"]
    cdd_run = national.metadata["cdd"]
    has_real_previous = previous.get("model") != "SIMULATED_FALLBACK"
    return dict(
        model="NOAA_NWS_FORECAST",
        run=national.observation_time.isoformat(),
        comparison_run=previous.get("run", "not_yet_refreshed"),
        hdd_run=hdd_run,
        hdd_comparison=previous.get("hdd_run", hdd_run) if has_real_previous else hdd_run,
        cdd_run=cdd_run,
        cdd_comparison=previous.get("cdd_run", cdd_run) if has_real_previous else cdd_run,
    )


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
        from .usage_recording_provider import UsageRecordingLLMProvider
        llm = UsageRecordingLLMProvider(get_default_llm_provider(), self.repo)
        self.llm = llm

        self.chief_trading_agent = ChiefTradingAgent(llm=llm)
        self.investment_committee = InvestmentCommittee(llm=llm)
        self.chief_investment_agent = ChiefInvestmentAgent(llm=llm)
        self.pipeline_agent = PipelineAgent(llm=llm)
        self.lng_agent = LNGAgent(llm=llm)
        self.power_market_agent = PowerMarketAgent(llm=llm)
        self.news_intelligence_agent = NewsIntelligenceAgent(llm=llm)
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
        self.alpha_memory_builder = MemoryBuilder()
        self.alpha_lesson_engine = LessonEngine()
        self.alpha_replay_engine = ReplayEngine()
        self.alpha_corroboration_engine = AlphaCorroborationEngine()
        self.alpha_brief_engine = BriefEngine()
        self.model_routing_engine = ModelRoutingEngine()
        self.retention_engine = RetentionEngine()
        self.enterprise_opportunity_engine = EnterpriseOpportunityEngine()
        self.enterprise_corroboration_engine = EnterpriseCorroborationEngine()
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
        self.recent_memory_records: list[MemoryRecord] = []
        self.recent_lesson_proposals: list[LessonProposal] = []
        self.recent_briefs: list[IntelligenceBrief] = []

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
        # "SIMULATED" until `refresh_fundamentals_from_public_data()`'s first
        # successful EIA storage fetch flips this to "PUBLIC" -- read by
        # `GET /fundamentals/storage/*` so the dashboard's classification badge
        # reflects what's actually behind `storage_baseline`, not a hardcoded guess.
        self.storage_baseline_classification: str = "SIMULATED"
        # Phase 1 free-data-feed integration (docs/data-sources.md): the fallback
        # used until `refresh_fundamentals_from_public_data()`'s first successful
        # NOAA fetch -- explicitly `SIMULATED_FALLBACK`, never a fake model name
        # (this replaces three previously-hardcoded dicts that falsely claimed
        # "GFS"/"ECMWF" while never actually calling either).
        self.weather_kwargs: dict = dict(
            model="SIMULATED_FALLBACK",
            run="not_yet_refreshed",
            comparison_run="not_yet_refreshed",
            hdd_run=2.8,
            hdd_comparison=2.2,
            cdd_run=4.0,
            cdd_comparison=4.5,
        )
        self._quality_service = DataQualityService()
        self._last_weather_snapshot: dict | None = None
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
            await self.repo.apply_row_level_security()
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
            for agent_type in agent_catalog.IMPLEMENTED_AGENT_TYPES:
                if agent_type != "RISK_GOVERNOR":
                    await self.apply_production_agent_version(agent_type)
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

    async def apply_production_agent_version(self, agent_type: str) -> bool:
        """Closes the gap `AgentVersionRow`'s docstring calls out: makes a `PRODUCTION`
        version actually change what the live agent does, instead of only being
        recorded for history (docs/agent-governance.md §4). Reads the agent_type's
        current `PRODUCTION` `AgentVersionRow` and applies it to the live `BaseAgent`
        instance resolved via `agent_catalog.resolve_agent_instance`:

        - `system_instructions` is copied onto `instance.system_instructions` verbatim
          (every agent's `_execute()` now forwards it as `system=` on every LLM call).
        - `model_name`, if set, rebuilds `instance.llm` via `build_llm_provider()` so the
          agent talks to the newly-approved model on its next call. An empty
          `model_name` leaves the existing provider in place (a version can change only
          the prompt without also having to pin a model).

        Also handles the "no PRODUCTION version exists" case honestly: resets
        `instance.system_instructions` to `None` (no override) rather than leaving a
        stale prompt in place, which matters when a rollback (`ROLLED_BACK` is a
        terminal transition straight off a `PRODUCTION` row -- `_AGENT_VERSION_
        TRANSITIONS` never auto-restores a prior version) leaves an agent_type with no
        current PRODUCTION row at all.

        Returns False when there's no live instance for this agent_type (e.g.
        `NEWS_INTELLIGENCE`, `RISK_GOVERNOR`) or no `PRODUCTION` version currently
        exists -- both real, expected states, not errors -- and True once the instance
        is confirmed in sync with a real PRODUCTION row. Called at boot right after
        `_seed_initial_agent_versions()` and from the admin transition endpoint every
        time a version is promoted to `PRODUCTION` or rolled back, so the live agents
        always match whatever is currently recorded as PRODUCTION."""
        instance = agent_catalog.resolve_agent_instance(self, agent_type)
        if instance is None:
            return False
        production = await self.repo.get_production_agent_version(agent_type)
        instance.system_instructions = (production or {}).get("system_instructions") or None
        model_name = (production or {}).get("model_name")
        if model_name:
            from .usage_recording_provider import UsageRecordingLLMProvider
            instance.llm = UsageRecordingLLMProvider(build_llm_provider(model_name), self.repo)
        return production is not None

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
        trade = self.trade_ideas.get(approval.trade_id)
        await self.repo.save_approval(
            approval_id=approval.id,
            trade_id=approval.trade_id,
            state=approval.state.value,
            actions=[a.model_dump(mode="json") for a in approval.actions],
            updated_at=approval.updated_at,
            organization_id=trade.organization_id if trade is not None else None,
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

        from config import get_settings as _get_settings

        cme_id = "mock_cme" if _get_settings().use_mock_market_data else "cme_live"
        cme = self.providers.get(cme_id)
        self.market_curve = await cme.fetch(FetchRequest(end=as_of))
        await self._persist_market_observations(self.market_curve)

        ice = self.providers.get("mock_ice")
        self.ttf_price = await ice.fetch(FetchRequest(end=as_of))

        news_provider = self.providers.get("mock_news")
        news_observations = await news_provider.fetch(FetchRequest(end=as_of))
        await self._run_news_intelligence(news_observations)

        try:
            await self.refresh_fundamentals_from_public_data()
        except Exception:
            logger.exception("Boot-time fundamentals refresh from public data failed; continuing on seeded/synthetic data")

    async def refresh_fundamentals_from_public_data(self) -> dict:
        """Phase 1 free-data-feed integration (docs/data-sources.md): fetches EIA
        (storage, production, consumption by sector, LNG exports, Henry Hub futures
        front-month) and NOAA (forecast temperature, national HDD/CDD approximation,
        severe weather alerts), quality-scores and persists every observation via
        `_persist_market_observations()`, and updates the two live-engine inputs
        whose real source data is granular enough to use honestly:

        - `self.storage_baseline`: EIA's real weekly storage history (current
          inventory, year-ago, 5-year average/low/high computed from real
          historical prints) -- only when `EIA_API_KEY` is configured; otherwise
          left untouched rather than blended with synthetic data.
        - `self.weather_kwargs`: NOAA's real national HDD/CDD approximation
          (`noaa.py`), diffed against the previous call's snapshot -- NOAA needs no
          API key, so this updates on every call.

        Deliberately does NOT touch `self.balances` (`GasBalanceDaily`, one row per
        day): EIA publishes natural gas fundamentals weekly/monthly, never daily --
        interpolating a fake daily shape from monthly totals would be estimation
        dressed up as real precision it doesn't have. `self.balances` stays the
        existing, honestly-SIMULATED daily balance engine until a real
        daily-granularity free source exists.

        Returns a summary dict for the caller (`worker.py`'s scheduled loop, boot)
        to log -- never raises; a fetch failure is caught, logged, and reported as
        an `error` `DataFeedEvent` per docs/data-sources.md's "prefer 'data
        unavailable' over displaying incorrect information."
        """
        summary: dict[str, Any] = {
            "eia_configured": False,
            "storage_updated": False,
            "weather_updated": False,
            "observations_persisted": 0,
        }

        eia = self.providers.get("eia")
        eia_health = await eia.health_check()
        summary["eia_configured"] = eia_health.status != "not_configured"
        if summary["eia_configured"]:
            try:
                # `length=260` (~5 years of weekly prints) is needed every cycle to
                # compute the year-ago/5-year comparisons in `_derive_storage_baseline`
                # -- `save_market_observation`'s revision-number check already makes
                # re-persisting already-known weeks a cheap no-op, so this re-fetch is
                # simpler than caching the history across cycles, at the cost of some
                # redundant EIA API calls each cycle (a documented Phase-1 simplification,
                # not a correctness concern -- EIA's public API has no rate limit this
                # cadence would meaningfully strain).
                storage_drafts = await eia.fetch(
                    FetchRequest(series_ids=["EIA.NG.STORAGE.LOWER48"], extra={"length": 260})
                )
                other_series_ids = [sid for sid in EIA_SERIES_MAP if sid != "EIA.NG.STORAGE.LOWER48"]
                other_drafts = await eia.fetch(FetchRequest(series_ids=other_series_ids))
                eia_drafts = storage_drafts + other_drafts
                scores = self._quality_service.score_batch(eia_drafts)
                for draft, score in zip(eia_drafts, scores):
                    draft.quality_score = score / 100.0  # ObservationDraft.quality_score is a 0-1 fraction
                await self._persist_market_observations(eia_drafts)
                summary["observations_persisted"] += len(eia_drafts)
                await self.repo.record_data_feed_event(
                    provider_id="eia",
                    event_type="manual_refresh",
                    status="success",
                    detail=f"Scheduled refresh fetched {len(eia_drafts)} observation(s).",
                    records_received=len(eia_drafts),
                    avg_quality_score=sum(scores) / len(scores) if scores else None,
                )

                new_baseline = _derive_storage_baseline(storage_drafts)
                if new_baseline is not None:
                    self.storage_baseline = new_baseline
                    self.storage_baseline_classification = "PUBLIC"
                    summary["storage_updated"] = True
            except Exception as exc:
                logger.exception("Scheduled EIA fundamentals refresh failed")
                await self.repo.record_data_feed_event(
                    provider_id="eia", event_type="manual_refresh", status="error", detail=str(exc)
                )

        noaa = self.providers.get("noaa_nws")
        try:
            weather_drafts = await noaa.fetch(FetchRequest())
            scores = self._quality_service.score_batch(weather_drafts)
            for draft, score in zip(weather_drafts, scores):
                draft.quality_score = score / 100.0  # ObservationDraft.quality_score is a 0-1 fraction
            await self._persist_market_observations(weather_drafts)
            summary["observations_persisted"] += len(weather_drafts)
            await self.repo.record_data_feed_event(
                provider_id="noaa_nws",
                event_type="manual_refresh",
                status="success",
                detail=f"Scheduled refresh fetched {len(weather_drafts)} observation(s).",
                records_received=len(weather_drafts),
                avg_quality_score=sum(scores) / len(scores) if scores else None,
            )

            new_weather_kwargs = _derive_weather_kwargs(weather_drafts, previous=self.weather_kwargs)
            if new_weather_kwargs is not None:
                self.weather_kwargs = new_weather_kwargs
                summary["weather_updated"] = True
        except Exception as exc:
            logger.exception("Scheduled NOAA weather refresh failed")
            await self.repo.record_data_feed_event(
                provider_id="noaa_nws", event_type="manual_refresh", status="error", detail=str(exc)
            )

        return summary

    async def _run_news_intelligence(self, raw_items: list[ObservationDraft]) -> None:
        """Milestone 1 follow-up (docs/agents.md §4): `NewsIntelligenceAgent` existed and
        was tested but had no live call site -- `agent_catalog.resolve_agent_instance`
        returned `None` for `NEWS_INTELLIGENCE` and a hand-rolled `_observations_to_news_
        events()` duplicated the agent's own ingest/classify logic inline instead of
        running it. This runs the real agent, logs its `AgentResult` like every other
        agent, and sets `self.news_events` from its structured output."""
        result = await self.news_intelligence_agent.run(raw_items=raw_items)
        self.agent_execution_log.append(result)
        self.news_events = [NewsEvent.model_validate(e) for e in result.outputs.get("events", [])]

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
            weather_kwargs=self.weather_kwargs,
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

        await self.generate_intelligence_brief()

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

    async def _run_chief_trading_research(self) -> ResearchCycleResult:
        """The fundamentals -> strategy pipeline shared by `run_chief_trading_cycle()`
        (platform-wide, on-demand) and `generate_enterprise_trade_idea()` (Milestone
        10 follow-up, org-scoped): runs the Chief Trading Agent's research cycle,
        appends every sub-agent's `AgentResult` to `agent_execution_log`, and runs
        AlphaSignal detection over the result -- everything both callers need before
        deciding what to do with `result.trade_ideas`. Factored out rather than
        duplicated so both trade-generation paths log and detect signals identically."""
        current_price = self.market_curve[0].value if self.market_curve else 3.0
        week_balance = sum(b.balance_bcf for b in self.balances[-7:])
        result = await self.chief_trading_agent.run_research_cycle(
            instrument=self.primary_instrument(),
            current_price=current_price,
            balances=self.balances,
            five_year_average_bcf=self.storage_baseline["five_year_average_bcf"],
            last_year_bcf=self.storage_baseline["year_ago_inventory_bcf"],
            as_of=date.today(),
            weather_kwargs=self.weather_kwargs,
            market_consensus_bcf=round(week_balance) + 3,
            disabled_agent_types=await self._disabled_agent_types(),
        )
        for res in (result.supply, result.demand, result.storage, result.weather, result.strategy, result.chief):
            if res is not None:
                self.agent_execution_log.append(res)

        await self._run_alpha_signal_detection(
            research_result=result, lng_result=None, power_result=None, pipeline_result=None
        )
        return result

    async def run_chief_trading_cycle(self) -> dict:
        """The Chief Trading Agent's on-demand research cycle -- the logic behind both
        `POST /agents/chief-trading/run` and (Milestone 8) `POST /admin/agents/
        CHIEF_TRADING_AGENT/run`. Deliberately lighter than boot's
        `_run_initial_research_cycle` (no pipeline/quant re-run) since this is a manual,
        on-demand trigger of just the fundamentals -> strategy -> committee pipeline."""
        result = await self._run_chief_trading_research()

        new_approvals = []
        for trade in result.trade_ideas:
            approval = await self.submit_trade_idea(trade)
            new_approvals.append(approval)

        return {
            "trade_ideas_generated": len(result.trade_ideas),
            "new_approval_ids": [a.id for a in new_approvals],
            "chief_summary": result.chief.reasoning_summary if result.chief else None,
        }

    async def generate_enterprise_trade_idea(self, *, organization_id: str) -> Approval | None:
        """Milestone 10 follow-up (docs/alpha-intelligence.md section 11.7): the
        "Enterprise-specific Chief Trading Agent" wired into the actual trade-
        generation/committee reasoning loop -- `ChatAgent._enterprise_data_query`
        already lets an enterprise customer *list* their registered datasets, but
        nothing before this generated a trade idea that actually incorporates an
        organization's own proprietary data. Runs the same research cycle
        `run_chief_trading_cycle()` runs (via the shared `_run_chief_trading_
        research()` helper), tags the resulting trade idea with `organization_id`
        so `submit_trade_idea()`'s enterprise corroboration step (`_corroborate_
        trade_with_enterprise_data`) cross-checks it against the organization's own
        positions before the Investment Committee deliberates, and submits it
        through the exact same `submit_trade_idea()` choke point every other trade
        idea goes through -- no separate, weaker trade-generation path for
        enterprise customers.

        `DirectionalStrategyAgent` (the only strategy agent in the pipeline today)
        produces at most one trade idea per research cycle, so only
        `result.trade_ideas[0]` is ever used. Returns `None` -- a real, expected
        outcome, not an error -- when this cycle produced no trade idea at all,
        e.g. the strategy agent's own data-driven SKIP when storage/weather
        signals disagree (see `strategy/directional.py`); the caller should say
        "no trade idea right now" honestly rather than fabricating one."""
        result = await self._run_chief_trading_research()
        if not result.trade_ideas:
            return None
        trade = result.trade_ideas[0].model_copy(update={"organization_id": organization_id})
        return await self.submit_trade_idea(trade)

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
                key=key,
                value=b["value"],
                rolling_window=b["rolling_window"],
                signal_emitted_history=b.get("signal_emitted_history", []),
                observed_at=b["observed_at"],
            )
            for key, b in raw_baselines.items()
        }
        portfolio_exposure = sum(
            abs(pos.quantity) * self.mark_price(instrument)
            for instrument, pos in self.paper_adapter.portfolio.positions.items()
        )
        risk_limit_usage = {
            "DAILY_LOSS": (
                self.current_daily_loss / self.risk_limits.max_daily_loss
                if self.risk_limits.max_daily_loss
                else 0.0
            ),
            "DRAWDOWN": (
                self.current_drawdown / self.risk_limits.max_drawdown if self.risk_limits.max_drawdown else 0.0
            ),
        }
        signals, updated_baselines = self.alpha_signal_detector.detect(
            research_result=research_result,
            lng_result=lng_result,
            power_result=power_result,
            pipeline_result=pipeline_result,
            market_curve=self.market_curve,
            baselines=baselines,
            portfolio_exposure=portfolio_exposure,
            risk_limit_usage=risk_limit_usage,
        )
        await self.repo.save_signal_baselines(
            {
                key: {
                    "value": snap.value,
                    "rolling_window": snap.rolling_window,
                    "signal_emitted_history": snap.signal_emitted_history,
                    "observed_at": snap.observed_at,
                }
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

    def _corroborate_trade_with_alpha_intelligence(self, trade: TradeIdea) -> TradeIdea:
        """Milestone 7 (docs/alpha-intelligence.md section 10): every Alpha*
        component through Milestone 6 runs strictly *after* a `TradeIdea` already
        exists -- a parallel, downstream analysis layer that never feeds back into
        trade generation. Restructuring `DirectionalStrategyAgent` itself to read
        Alpha* output would risk destabilizing already-tested trade-generation
        logic for uncertain benefit. Instead, `submit_trade_idea()` is the single
        choke point every trade idea passes through before the Investment
        Committee deliberates on it -- so this is where the loop closes: cross-
        checking the trade against `self.recent_signals`/`self.recent_
        consensus_views` (already fresh by this point in both `_run_initial_
        research_cycle` and `run_chief_trading_cycle`, since alpha signal
        detection -- and, at boot, alpha consensus -- run before the trade-
        submission loop) and merging the result onto the trade's own `catalysts`/
        `supporting_data`/`source_citations`/`risks` before `BullAgent` (reads
        `catalysts`) and `SkepticAgent` (reads `source_citations`/
        `supporting_data`) ever see it."""
        consensus_view = next(
            (v for v in reversed(self.recent_consensus_views) if v.consensus_type == "MARKET_DIRECTION"),
            None,
        )
        corroboration = self.alpha_corroboration_engine.corroborate(
            trade=trade, signals=self.recent_signals, consensus_view=consensus_view
        )
        if corroboration.is_empty:
            return trade
        return trade.model_copy(
            update={
                "catalysts": trade.catalysts + corroboration.additional_catalysts,
                "supporting_data": trade.supporting_data + corroboration.additional_supporting_data,
                "source_citations": trade.source_citations + corroboration.additional_citations,
                "risks": trade.risks + corroboration.additional_risks,
            }
        )

    async def submit_trade_idea(self, trade: TradeIdea) -> Approval:
        trade = self._corroborate_trade_with_alpha_intelligence(trade)
        trade = await self._corroborate_trade_with_enterprise_data(trade)
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
        await self.repo.save_committee_decision(trade.trade_id, decision, organization_id=trade.organization_id)

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
        await self.repo.save_risk_check(trade.trade_id, risk_check, organization_id=trade.organization_id)
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

        await self._build_decision_memory(trade, committee, risk_check, analysis, forecast)

        return {"post_trade_analysis": analysis, "exit_price": exit_fill_price}

    async def _build_decision_memory(
        self,
        trade: TradeIdea,
        committee: InvestmentCommitteeDecision,
        risk_check: RiskCheckResult,
        post_trade: PostTradeAnalysis,
        forecast: PriceForecast | None,
    ) -> None:
        """AlphaMemory(TM)'s integration point (docs/alpha-intelligence.md section 8):
        runs immediately after `close_trade()` persists its `PostTradeAnalysis`,
        turning that already-computed decision record into a durable `MemoryRecord`
        plus a human-reviewable `LessonProposal` -- never an automatic feedback loop
        into any production model or threshold."""
        memory = self.alpha_memory_builder.build_decision_memory(
            trade=trade, committee=committee, risk_check=risk_check, post_trade=post_trade, forecast=forecast
        )
        await self.repo.save_memory_record(memory)
        self.recent_memory_records.append(memory)
        self.recent_memory_records = self.recent_memory_records[-50:]
        await self.event_bus.publish(
            DomainEvent(
                event_type=EventType.MEMORY_RECORD_CREATED,
                source_service="alpha_service",
                payload=memory.model_dump(mode="json"),
                lineage_ids=[str(trade.trade_id)],
            )
        )

        lesson = self.alpha_lesson_engine.propose(memory)
        if lesson is not None:
            await self.repo.save_lesson_proposal(lesson)
            self.recent_lesson_proposals.append(lesson)
            self.recent_lesson_proposals = self.recent_lesson_proposals[-50:]
            await self.event_bus.publish(
                DomainEvent(
                    event_type=EventType.LESSON_PROPOSED,
                    source_service="alpha_service",
                    payload=lesson.model_dump(mode="json"),
                    lineage_ids=[str(memory.id)],
                )
            )

    async def review_lesson_proposal(self, lesson_id: str, *, status: str, reviewed_by: str) -> dict | None:
        """Human review of a `LessonProposal` (docs/alpha-intelligence.md section 8) --
        the only way a proposal's status ever changes; approving it here does not
        feed back into any engine or threshold automatically."""
        updated = await self.repo.update_lesson_proposal_status(
            lesson_id, status=status, reviewed_by=reviewed_by, reviewed_at=datetime.now(timezone.utc)
        )
        if updated is None:
            return None
        for i, cached in enumerate(self.recent_lesson_proposals):
            if str(cached.id) == lesson_id:
                self.recent_lesson_proposals[i] = LessonProposal.model_validate(updated)
                break
        await self.event_bus.publish(
            DomainEvent(event_type=EventType.LESSON_REVIEWED, source_service="alpha_service", payload=updated)
        )
        return updated

    async def _persist_market_observations(self, observations: list[ObservationDraft]) -> None:
        """AlphaReplay(TM)'s bitemporal capture point (docs/alpha-intelligence.md
        section 9): persists each observation into the revision-history-aware
        `alpha_market_observations` store via `SqlAppRepository.
        save_market_observation()`, publishing `OBSERVATION_REVISED` whenever a
        later revision supersedes an earlier one for the same series_id+
        observation_time. Honest about scope: today this only runs from
        `_seed_market_and_fundamentals()` (boot), since nothing in this codebase
        yet periodically re-fetches `market_curve` after boot (`worker.py` only
        reads the boot-time snapshot) -- real revision supersession activates
        automatically once a future milestone adds periodic re-fetching or a real
        (non-mock) provider republishes a corrected historical value; until then,
        Milestone 6 captures one snapshot per process lifetime, not a deep
        revision history."""
        for draft in observations:
            obs = TimeSeriesObservation(**draft.model_dump())
            await self.repo.save_market_observation(obs)
            if obs.revision_number > 0:
                await self.event_bus.publish(
                    DomainEvent(
                        event_type=EventType.OBSERVATION_REVISED,
                        source_service="alpha_service",
                        payload=obs.model_dump(mode="json"),
                    )
                )

    async def compute_as_of_replay(
        self,
        *,
        market: str | None = None,
        as_of: datetime,
        organization_id: str | None = None,
        platform_only: bool = False,
    ) -> AsOfReplayResult:
        """AlphaReplay(TM)'s integration point (docs/alpha-intelligence.md section
        9): reconstructs everything the Alpha Intelligence Layer itself knew and
        concluded as of `as_of`, using only the bitemporal repository queries that
        already enforce "no look-ahead" (`list_market_observations_as_of()`'s
        `as_of` filter, and the `until` parameter on every other Alpha* list
        method) -- this method performs no additional filtering of its own, so
        there is exactly one place look-ahead bias could be introduced.
        `platform_only` (docs/alpha-intelligence.md section 11.1, Milestone 9)
        threads the same tenant-isolation restriction as every other Alpha* list
        endpoint into the replay reconstruction."""
        market = market or self.primary_instrument()
        price_observations_raw = await self.repo.list_market_observations_as_of(as_of=as_of)
        signals_raw = await self.repo.list_signals(
            market=market, until=as_of, organization_id=organization_id, platform_only=platform_only, limit=50
        )
        impacts_raw = await self.repo.list_impact_analyses(
            organization_id=organization_id, platform_only=platform_only, until=as_of, limit=50
        )
        consensus_raw = await self.repo.list_consensus_views(
            market=market, organization_id=organization_id, platform_only=platform_only, until=as_of, limit=50
        )
        scenario_raw = await self.repo.list_scenario_runs(
            organization_id=organization_id, platform_only=platform_only, until=as_of, limit=50
        )
        memory_raw = await self.repo.list_memory_records(
            market=market, organization_id=organization_id, platform_only=platform_only, until=as_of, limit=50
        )
        return self.alpha_replay_engine.assemble(
            market=market,
            as_of=as_of,
            price_observations=[TimeSeriesObservation.model_validate(o) for o in price_observations_raw],
            signals=[Signal.model_validate(s) for s in signals_raw],
            impacts=[ImpactAnalysis.model_validate(i) for i in impacts_raw],
            consensus_views=[ConsensusView.model_validate(c) for c in consensus_raw],
            scenario_runs=[ScenarioRunResult.model_validate(r) for r in scenario_raw],
            memory_records=[MemoryRecord.model_validate(m) for m in memory_raw],
        )

    async def compute_market_bias(self, *, market: str | None = None) -> MarketBiasResult:
        """Phase 1 free-data-feed integration, Round 2 (spec section 26): gathers
        this platform's own real/synthetic inputs -- `weather_kwargs`,
        `storage_baseline`, recent `GasBalanceDaily` history, the M1 price window,
        and the market's latest platform-wide `ConsensusView` -- and hands them to
        `alpha_service.compute_market_bias()`, the pure deterministic scorer. Never
        asks the LLM to decide the bias; every point in the result traces back to
        one of these already-real-or-honestly-synthetic inputs."""
        market = market or self.primary_instrument()
        consensus = await self.repo.get_latest_consensus_view_for_market(market)
        # `self.price_history` is append-ordered oldest-first (see `generate_price_history`),
        # so the last 14 entries are already oldest-to-newest within that window --
        # exactly what `compute_market_bias`'s momentum driver expects.
        recent_prices = [obs.value for obs in self.price_history[-14:]] if self.price_history else []
        return compute_market_bias(
            weather_kwargs=self.weather_kwargs,
            storage_baseline=self.storage_baseline,
            recent_balances=self.balances,
            recent_prices=recent_prices,
            consensus_bull_probability=consensus["bull_probability"] if consensus else None,
            consensus_bear_probability=consensus["bear_probability"] if consensus else None,
            consensus_confidence=consensus["confidence"] if consensus else None,
        )

    async def generate_intelligence_brief(
        self,
        *,
        market: str | None = None,
        organization_id: str | None = None,
        period_hours: int = 16,
    ) -> IntelligenceBrief:
        """The Overnight Intelligence Brief (docs/alpha-intelligence.md section 10,
        Milestone 7): a single cross-component digest of what AlphaSignal/
        AlphaImpact/AlphaConsensus/AlphaScenario/AlphaMemory each concluded over
        the last `period_hours` (16h default -- an overnight window, not a full
        day, since this runs once per boot/full research cycle rather than on a
        calendar schedule). Only reachable from `_run_initial_research_cycle`
        (boot's full cycle) -- `run_chief_trading_cycle`'s lighter on-demand path
        doesn't generate a brief, matching the same boot-cycle-only scope already
        established for `_run_alpha_consensus`."""
        market = market or self.primary_instrument()
        period_end = datetime.now(timezone.utc)
        period_start = period_end - timedelta(hours=period_hours)
        signals_raw = await self.repo.list_signals(
            market=market, organization_id=organization_id, since=period_start, limit=50
        )
        impacts_raw = await self.repo.list_impact_analyses(
            organization_id=organization_id, since=period_start, limit=50
        )
        consensus_raw = await self.repo.list_consensus_views(
            market=market, organization_id=organization_id, since=period_start, limit=50
        )
        scenario_raw = await self.repo.list_scenario_runs(
            organization_id=organization_id, since=period_start, limit=50
        )
        lessons_raw = await self.repo.list_lesson_proposals(
            status="PENDING", organization_id=organization_id, limit=50
        )
        brief = self.alpha_brief_engine.compose(
            market=market,
            period_start=period_start,
            period_end=period_end,
            organization_id=organization_id,
            signals=[Signal.model_validate(s) for s in signals_raw],
            impacts=[ImpactAnalysis.model_validate(i) for i in impacts_raw],
            consensus_views=[ConsensusView.model_validate(c) for c in consensus_raw],
            scenario_runs=[ScenarioRunResult.model_validate(r) for r in scenario_raw],
            lesson_proposals=[LessonProposal.model_validate(lp) for lp in lessons_raw],
        )
        await self.repo.save_intelligence_brief(brief)
        self.recent_briefs.append(brief)
        self.recent_briefs = self.recent_briefs[-50:]
        await self.event_bus.publish(
            DomainEvent(
                event_type=EventType.INTELLIGENCE_BRIEF_GENERATED,
                source_service="alpha_service",
                payload=brief.model_dump(mode="json"),
            )
        )
        return brief

    async def apply_retention_policy(
        self, *, organization_id: str | None, data_classification: EnterpriseDataClassification
    ) -> dict:
        """Tenant-isolation retrofit (docs/alpha-intelligence.md section 11.1,
        Milestone 9): resolves the retention policy visible to `organization_id`
        for `data_classification` (`RetentionEngine.resolve_retention_days`,
        organization override winning over the platform default), then purges
        every `EnterpriseRecordRow` older than the resulting cutoff across every
        dataset of that (organization, classification) pair. Returns a summary
        dict rather than raising when no policy is configured -- no purge is a
        legitimate, common outcome, not an error."""
        policies_raw = await self.repo.list_retention_policies(organization_id=organization_id)
        policies = [RetentionPolicy.model_validate(p) for p in policies_raw]
        retention_days = self.retention_engine.resolve_retention_days(
            data_classification=data_classification, policies=policies, organization_id=organization_id
        )
        cutoff = self.retention_engine.compute_cutoff(retention_days, now=datetime.now(timezone.utc))
        if cutoff is None:
            return {
                "organization_id": organization_id,
                "data_classification": data_classification.value,
                "retention_days": None,
                "datasets_checked": 0,
                "records_purged": 0,
            }

        datasets = await self.repo.list_enterprise_datasets(organization_id=organization_id)
        matching = [d for d in datasets if d["classification"] == data_classification.value]
        total_purged = 0
        for dataset in matching:
            total_purged += await self.repo.purge_enterprise_records_for_retention(
                dataset_id=dataset["id"], cutoff=cutoff
            )
        result = {
            "organization_id": organization_id,
            "data_classification": data_classification.value,
            "retention_days": retention_days,
            "datasets_checked": len(matching),
            "records_purged": total_purged,
        }
        await self.event_bus.publish(
            DomainEvent(event_type=EventType.RETENTION_PURGE_COMPLETED, source_service="enterprise_data_service", payload=result)
        )
        return result

    # The `agent_type` `_load_enterprise_positions()` presents to `agent_is_entitled()`
    # for AGENT-type EnterpriseDataEntitlement checks -- the principal_id an admin
    # grants to restrict which datasets this read path may see.
    ENTERPRISE_POSITION_READER_AGENT_TYPE = "ENTERPRISE_OPPORTUNITY_ENGINE"

    async def _load_enterprise_positions(self, organization_id: str) -> list[EnterprisePosition]:
        """Reads `organization_id`'s own `POSITION`/`PORTFOLIO`-domain enterprise
        records and parses each into an `EnterprisePosition` (silently skipping any
        record `EnterprisePosition.from_record` can't recognize a market/instrument
        field on -- see that method's docstring). Factored out of
        `generate_enterprise_opportunities()` so `_corroborate_trade_with_enterprise_
        data()` (docs/alpha-intelligence.md section 11, Milestone 10 follow-up) can
        reuse the exact same read path rather than duplicating it.

        Gap-closure follow-up: datasets are now also filtered through
        `agent_is_entitled()`, checking `AGENT`-type `EnterpriseDataEntitlement`
        grants against `ENTERPRISE_POSITION_READER_AGENT_TYPE` above -- this pipeline
        has no per-caller human principal (it runs org-wide, not on behalf of one
        user), so it was the one enterprise read path `dataset_is_entitled()`
        genuinely couldn't reach; `AGENT` grants exist precisely for this shape of
        caller. A dataset with no `AGENT`-type grants stays visible (backward-
        compatible default, unchanged behavior)."""
        datasets = await self.repo.list_enterprise_datasets(organization_id=organization_id)
        position_datasets = [
            d for d in datasets if d["domain"] in (EnterpriseDataDomain.POSITION.value, EnterpriseDataDomain.PORTFOLIO.value)
        ]
        entitled_position_datasets = []
        for dataset in position_datasets:
            raw_entitlements = await self.repo.list_enterprise_data_entitlements(dataset["id"])
            entitlements = [EnterpriseDataEntitlement.model_validate(e) for e in raw_entitlements]
            if agent_is_entitled(entitlements=entitlements, agent_type=self.ENTERPRISE_POSITION_READER_AGENT_TYPE):
                entitled_position_datasets.append(dataset)
        position_datasets = entitled_position_datasets
        positions: list[EnterprisePosition] = []
        for dataset in position_datasets:
            records = await self.repo.list_enterprise_records(dataset["id"], limit=200)
            for record in records:
                pos = EnterprisePosition.from_record(
                    dataset_id=dataset["id"], record_id=record["id"], row_data=record["row_data"]
                )
                if pos is not None:
                    positions.append(pos)
        return positions

    async def _corroborate_trade_with_enterprise_data(self, trade: TradeIdea) -> TradeIdea:
        """Milestone 10 follow-up (docs/alpha-intelligence.md section 11): the
        Enterprise Data Platform's own analog of `_corroborate_trade_with_alpha_
        intelligence` -- cross-checks a trade against the trade's own organization's
        proprietary `EnterprisePosition` holdings via `EnterpriseCorroborationEngine`
        and merges the result onto `supporting_data`/`source_citations`/`risks`
        before the Investment Committee ever sees it. A no-op (returns `trade`
        unchanged) whenever `trade.organization_id is None` -- most trades are
        platform-wide, not generated for a specific enterprise customer, and there is
        no principled organization to load positions for in that case."""
        if trade.organization_id is None:
            return trade
        positions = await self._load_enterprise_positions(trade.organization_id)
        corroboration = self.enterprise_corroboration_engine.corroborate(trade=trade, positions=positions)
        if corroboration.is_empty:
            return trade
        return trade.model_copy(
            update={
                "supporting_data": trade.supporting_data + corroboration.additional_supporting_data,
                "source_citations": trade.source_citations + corroboration.additional_citations,
                "risks": trade.risks + corroboration.additional_risks,
            }
        )

    async def generate_enterprise_opportunities(self, *, organization_id: str) -> list[EnterpriseOpportunity]:
        """`EnterpriseOpportunityEngine`'s integration point (docs/alpha-intelligence.md
        section 11.7, Milestone 10): cross-references `organization_id`'s own
        `POSITION`/`PORTFOLIO`-domain enterprise records against recent Alpha
        Intelligence signals/consensus, persists every candidate as a `PENDING`
        `EnterpriseOpportunity`, and publishes `OPPORTUNITY_PROPOSED`. Always scoped
        to one organization's own registered datasets -- there is no platform-wide
        opportunity feed, and this does not yet check per-dataset
        `EnterpriseDataEntitlement` grants (docs/alpha-intelligence.md section 11.2
        already flags that non-admin, per-dataset entitlement enforcement isn't
        wired into any read path yet; this reuses that same honest limitation
        rather than pretending to solve it here)."""
        positions = await self._load_enterprise_positions(organization_id)

        since = datetime.now(timezone.utc) - timedelta(hours=24 * 30)
        signals_raw = await self.repo.list_signals(organization_id=organization_id, since=since, limit=200)
        consensus_raw = await self.repo.list_consensus_views(organization_id=organization_id, since=since, limit=200)
        candidates = self.enterprise_opportunity_engine.generate(
            positions=positions,
            signals=[Signal.model_validate(s) for s in signals_raw],
            consensus_views=[ConsensusView.model_validate(c) for c in consensus_raw],
        )

        created: list[EnterpriseOpportunity] = []
        for candidate in candidates:
            opportunity = EnterpriseOpportunity(
                organization_id=organization_id,
                opportunity_type=EnterpriseOpportunityType(candidate.opportunity_type),
                market=candidate.market,
                title=candidate.title,
                summary=candidate.summary,
                confidence=candidate.confidence,
                supporting_signal_ids=candidate.supporting_signal_ids,
                supporting_consensus_id=candidate.supporting_consensus_id,
                related_dataset_id=candidate.related_dataset_id,
                related_record_id=candidate.related_record_id,
            )
            await self.repo.save_enterprise_opportunity(opportunity)
            created.append(opportunity)
            await self.event_bus.publish(
                DomainEvent(
                    event_type=EventType.OPPORTUNITY_PROPOSED,
                    source_service="enterprise_data_service",
                    payload=opportunity.model_dump(mode="json"),
                )
            )
        return created

    async def generate_enterprise_opportunities_for_all_organizations(self) -> dict[str, list[EnterpriseOpportunity]]:
        """Milestone 10 follow-up (docs/alpha-intelligence.md section 11.7): the scheduled
        cadence `generate_enterprise_opportunities()` itself never had -- that method was
        (and still is) reachable admin/user-triggered only, via `POST /alpha/enterprise/
        opportunities/generate`. This enumerates every distinct `organization_id` that has
        registered at least one enterprise dataset (platform-wide `list_enterprise_datasets()`,
        no `organization_id` filter) and runs opportunity generation for each -- called
        periodically by `worker.py`, the same home the Chief Trading Agent's own periodic
        research cycle already uses, rather than inventing a second scheduling mechanism.
        An organization with no registered datasets is never iterated (nothing to
        cross-reference against, same as calling `generate_enterprise_opportunities()` for it
        directly would return `[]`)."""
        all_datasets = await self.repo.list_enterprise_datasets()
        organization_ids = sorted({d["organization_id"] for d in all_datasets})
        results: dict[str, list[EnterpriseOpportunity]] = {}
        for organization_id in organization_ids:
            results[organization_id] = await self.generate_enterprise_opportunities(organization_id=organization_id)
        return results

    async def apply_retention_policies_for_all_organizations(self) -> list[dict]:
        """Gap-closure follow-up (docs/alpha-intelligence.md section 11.6):
        `apply_retention_policy()` itself had no scheduled cadence -- admin/API-
        triggered only, via `POST /admin/retention-policies/apply`. Mirrors
        `generate_enterprise_opportunities_for_all_organizations()` exactly: enumerates
        every distinct `(organization_id, classification)` pair that actually has at
        least one registered dataset (platform-wide `list_enterprise_datasets()`, no
        filter) and applies that pair's retention policy -- a pair with no policy
        configured is a legitimate no-op (`apply_retention_policy` already returns a
        zero-purge summary rather than raising), not skipped outright, so the result
        list stays a complete audit trail of every pair checked. Called periodically by
        `worker.py`, the same home the opportunity-generation cadence already uses."""
        all_datasets = await self.repo.list_enterprise_datasets()
        pairs = sorted({(d["organization_id"], d["classification"]) for d in all_datasets})
        results: list[dict] = []
        for organization_id, classification in pairs:
            results.append(
                await self.apply_retention_policy(
                    organization_id=organization_id, data_classification=EnterpriseDataClassification(classification)
                )
            )
        return results

    async def review_enterprise_opportunity(self, opportunity_id: str, *, status: str, reviewed_by: str) -> dict | None:
        updated = await self.repo.update_enterprise_opportunity_status(
            opportunity_id, status=status, reviewed_by=reviewed_by, reviewed_at=datetime.now(timezone.utc)
        )
        if updated is None:
            return None
        await self.event_bus.publish(
            DomainEvent(event_type=EventType.OPPORTUNITY_REVIEWED, source_service="enterprise_data_service", payload=updated)
        )
        return updated

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
