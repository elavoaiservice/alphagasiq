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
from agents_service import ChiefInvestmentAgent, ChiefTradingAgent, InvestmentCommittee
from config import get_settings
from data_sdk import FetchRequest, ProviderRegistry
from data_service.providers.mock_market_data import MockCMEProvider, MockICEProvider
from data_service.providers.mock_news import MockNewsProvider
from data_service.registry import build_default_registry
from fundamentals_service.lng import LNGTerminalState, compute_netback
from fundamentals_service.power_burn import PowerMarketState, estimate_power_burn_bcf_d
from fundamentals_service.seed import (
    generate_daily_balances,
    seed_lng_terminals,
    seed_power_markets,
    seed_storage_baseline,
)
from paper_execution_service import PaperExecutionAdapter
from risk_service.governor import RiskContext, RiskGovernor
from risk_service.limits import default_risk_limits
from risk_service.metrics import PositionSnapshot, summarize
from schemas import (
    AgentResult,
    DataClassification,
    InvestmentCommitteeDecision,
    NewsEvent,
    ObservationDraft,
    RiskCheckResult,
    RiskLimits,
    RiskVerdict,
    TradeIdea,
)

from .models import Approval, ApprovalState, ChatSession

PRIMARY_INSTRUMENT = "NGZ26"


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

        self.trade_ideas: dict[UUID, TradeIdea] = {}
        self.committee_decisions: dict[UUID, InvestmentCommitteeDecision] = {}
        self.risk_checks: dict[UUID, RiskCheckResult] = {}
        self.approvals: dict[UUID, Approval] = {}
        self.decision_journal: dict[UUID, list[dict]] = {}  # trade_id -> append-only entries

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

        cme = self.providers.get("mock_cme")
        self.market_curve = await cme.fetch(FetchRequest(end=as_of))

        ice = self.providers.get("mock_ice")
        self.ttf_price = await ice.fetch(FetchRequest(end=as_of))

        news_provider = self.providers.get("mock_news")
        news_observations = await news_provider.fetch(FetchRequest(end=as_of))
        self.news_events = _observations_to_news_events(news_observations)

    async def _run_initial_research_cycle(self) -> None:
        today = date.today()
        current_price = self.market_curve[0].value if self.market_curve else 3.0
        week_balance = sum(b.balance_bcf for b in self.balances[-7:])
        market_consensus_bcf = round(week_balance) + 3  # illustrative "street" estimate

        result = await self.chief_trading_agent.run_research_cycle(
            instrument=PRIMARY_INSTRUMENT,
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

        for trade in result.trade_ideas:
            await self.submit_trade_idea(trade)

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
