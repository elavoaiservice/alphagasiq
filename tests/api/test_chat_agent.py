"""Unit tests for `ChatAgent`'s per-topic tool authorization (docs/access-model.md
§6, spec §28 "Chat Authorization"). These are isolated from the router-level
`chief_agent.chat` gate (covered by `test_api.py`'s chat tests) — a fake, minimal
`AppState` stand-in plus a monkeypatched `get_effective_permissions` lets these
exercise `ChatAgent.ask()`'s decline-before-dispatch logic directly, including
proving that a declined topic never touches `AppState` at all (the fake state
below has no `portfolio_risk_summary`, so a wrongly-dispatched `top_risks` call
would raise `AttributeError` rather than silently pass).
"""

from __future__ import annotations

import pytest
from agent_sdk import MockLLMProvider
from api_app import chat_agent as chat_agent_module
from api_app.auth import Role, User
from api_app.chat_agent import ChatAgent


class _FakeState:
    def __init__(self):
        self.trade_ideas = {}


@pytest.fixture
def user():
    return User(user_id="u-test", email="test@example.com", display_name="Test User", roles=[Role.VIEWER])


async def test_permitted_topic_calls_the_real_tool_and_reports_metadata(monkeypatch, user):
    async def fake_permissions(_user, _state):
        return {"trading_recommendations.view"}

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    agent = ChatAgent(llm=MockLLMProvider())

    result = await agent.ask("Why are we bullish?", _FakeState(), user)

    assert result.access_granted is True
    assert result.tool_used == "why_bias"
    assert result.permission_required == "trading_recommendations.view"
    assert "No active trade ideas" in result.content
    assert result.latency_ms is not None and result.latency_ms >= 0


async def test_restricted_topic_is_declined_before_touching_state(monkeypatch, user):
    async def fake_permissions(_user, _state):
        return {"chief_agent.chat"}  # deliberately no portfolio.view

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    agent = ChatAgent(llm=MockLLMProvider())

    # `_FakeState` has no `portfolio_risk_summary` -- if the permission check were
    # bypassed and the real tool were dispatched anyway, this would raise
    # AttributeError instead of returning a declined result.
    result = await agent.ask("What is the largest risk in my portfolio?", _FakeState(), user)

    assert result.access_granted is False
    assert result.tool_used == "top_risks"
    assert result.permission_required == "portfolio.view"
    assert "portfolio.view" in result.content


async def test_declined_topic_never_calls_the_llm(monkeypatch, user):
    """The LLM is only ever handed real retrieved facts, never asked to fabricate
    an answer to a restricted question."""

    class _ExplodingLLM(MockLLMProvider):
        async def complete(self, *args, **kwargs):
            raise AssertionError("LLM must not be invoked for a declined topic")

    async def fake_permissions(_user, _state):
        return set()

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    agent = ChatAgent(llm=_ExplodingLLM())

    result = await agent.ask("Why are we bullish?", _FakeState(), user)
    assert result.access_granted is False


async def test_what_changed_overnight_routes_to_alphasignal_tool(monkeypatch, user):
    """AlphaSignalTool (docs/alpha-intelligence.md section 43): "overnight"/"material
    change" phrasing routes to the new topic, requires `alpha_signals.view`, and reads
    `state.recent_signals` -- distinct from the pre-existing `_what_changed` topic,
    which reads the raw agent execution log instead."""
    from schemas import Signal, SignalType

    async def fake_permissions(_user, _state):
        return {"alpha_signals.view"}

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    agent = ChatAgent(llm=MockLLMProvider())

    state = _FakeState()
    state.recent_signals = [
        Signal(
            signal_type=SignalType.STORAGE_CHANGE,
            category="fundamentals",
            headline="Storage forecast shifted",
            description="test signal",
            materiality_score=91.0,
            confidence=0.8,
        )
    ]

    result = await agent.ask("What changed overnight?", state, user)

    assert result.access_granted is True
    assert result.tool_used == "what_changed_overnight"
    assert result.permission_required == "alpha_signals.view"
    assert "Storage forecast shifted" in result.content


async def test_what_changed_overnight_declined_without_permission(monkeypatch, user):
    async def fake_permissions(_user, _state):
        return set()

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    agent = ChatAgent(llm=MockLLMProvider())

    # _FakeState has no `recent_signals` attribute -- a wrongly-dispatched tool call
    # would raise AttributeError instead of returning a declined result.
    result = await agent.ask("What changed overnight?", _FakeState(), user)

    assert result.access_granted is False
    assert result.tool_used == "what_changed_overnight"
    assert "alpha_signals.view" in result.content


async def test_why_does_it_matter_routes_to_alphaimpact_tool(monkeypatch, user):
    """AlphaImpactTool (docs/alpha-intelligence.md section 43): "why does it matter"
    routes to a new topic, requires `alpha_impacts.view`, and reads
    `state.recent_impacts` -- matched to the highest-materiality signal in
    `state.recent_signals` by `signal_id`."""
    from alpha_service import ImpactEngine
    from schemas import Signal, SignalType

    async def fake_permissions(_user, _state):
        return {"alpha_impacts.view"}

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    agent = ChatAgent(llm=MockLLMProvider())

    sig = Signal(
        signal_type=SignalType.STORAGE_CHANGE,
        category="fundamentals",
        headline="Storage forecast shifted",
        description="test signal",
        materiality_score=91.0,
        confidence=0.8,
    )
    state = _FakeState()
    state.recent_signals = [sig]
    state.recent_impacts = [ImpactEngine().analyze(sig)]

    result = await agent.ask("Why does it matter?", state, user)

    assert result.access_granted is True
    assert result.tool_used == "why_does_it_matter"
    assert result.permission_required == "alpha_impacts.view"
    assert "STORAGE_CHANGE" in result.content


async def test_why_does_it_matter_declined_without_permission(monkeypatch, user):
    async def fake_permissions(_user, _state):
        return set()

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    agent = ChatAgent(llm=MockLLMProvider())

    # _FakeState has no `recent_impacts` attribute -- a wrongly-dispatched tool call
    # would raise AttributeError instead of returning a declined result.
    result = await agent.ask("Why does it matter?", _FakeState(), user)

    assert result.access_granted is False
    assert result.tool_used == "why_does_it_matter"
    assert "alpha_impacts.view" in result.content


async def test_agent_consensus_routes_to_alphaconsensus_tool(monkeypatch, user):
    """AlphaConsensusTool (docs/alpha-intelligence.md section 43): "do the agents
    agree" phrasing routes to the new topic, requires `alpha_consensus.view`, and
    reads `state.recent_consensus_views` -- distinct from `disagree` (which routes
    to the pre-existing `most_disagreeing_agent` topic)."""
    from alpha_service import ConsensusEngine
    from schemas import AgentForecast, AgentType, SignalDirection

    async def fake_permissions(_user, _state):
        return {"alpha_consensus.view"}

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    agent = ChatAgent(llm=MockLLMProvider())

    forecasts = [
        AgentForecast(
            agent_id="storage-agent",
            agent_type=AgentType.STORAGE,
            agent_version="1.0.0",
            forecast_type="STORAGE_WEEKLY",
            target="STORAGE_BCF",
            forecast_value=88.0,
            direction=SignalDirection.BULLISH,
            probability=0.7,
            confidence=0.7,
        )
    ]
    view = ConsensusEngine().compute(
        consensus_type="STORAGE_FORECAST",
        target="STORAGE_BCF",
        market="HENRY_HUB",
        forecasts=forecasts,
        scores={},
        market_consensus_value=86.0,
    )
    state = _FakeState()
    state.recent_consensus_views = [view]

    result = await agent.ask("Do the agents agree?", state, user)

    assert result.access_granted is True
    assert result.tool_used == "agent_consensus"
    assert result.permission_required == "alpha_consensus.view"
    assert "HENRY_HUB" in result.content


async def test_agent_consensus_declined_without_permission(monkeypatch, user):
    async def fake_permissions(_user, _state):
        return set()

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    agent = ChatAgent(llm=MockLLMProvider())

    # _FakeState has no `recent_consensus_views` attribute -- a wrongly-dispatched
    # tool call would raise AttributeError instead of returning a declined result.
    result = await agent.ask("Do the agents agree?", _FakeState(), user)

    assert result.access_granted is False
    assert result.tool_used == "agent_consensus"
    assert "alpha_consensus.view" in result.content


async def test_disagree_still_routes_to_most_disagreeing_agent(monkeypatch, user):
    """Regression guard: adding the "agree" keyword for AlphaConsensus must not
    steal "disagree" questions away from the pre-existing disagreement topic --
    the `most_disagreeing_agent` elif branch is checked first in `_route`."""

    async def fake_permissions(_user, _state):
        return {"trading_recommendations.view"}

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    agent = ChatAgent(llm=MockLLMProvider())

    state = _FakeState()
    state.committee_decisions = {}
    result = await agent.ask("Which agent disagrees the most?", state, user)

    assert result.tool_used == "most_disagreeing_agent"


class _FakePortfolio:
    def __init__(self):
        self.positions = {}


class _FakePaperAdapter:
    def __init__(self):
        self.portfolio = _FakePortfolio()


def _scenario_capable_fake_state() -> _FakeState:
    """A `_FakeState` extended with just the attributes `_run_named_scenario`/
    `_scenario_comparison` read: an empty paper book (so `run_scenario`'s P&L math
    runs against zero positions, exercising the real engine without needing a
    synthetic trade) and a real `ScenarioEngine` (pure, no I/O)."""
    from alpha_service import ScenarioEngine

    state = _FakeState()
    state.paper_adapter = _FakePaperAdapter()
    state.alpha_scenario_engine = ScenarioEngine()
    state.mark_price = lambda instrument: 3.0
    return state


async def test_run_named_scenario_composes_an_explicit_percentage_shock(monkeypatch, user):
    """AlphaScenarioTool (docs/alpha-intelligence.md section 7): a question naming
    both a scenario and an explicit percentage stacks a custom price shock via
    `ScenarioEngine.compose()` rather than only ever running the named scenario
    alone -- the response must reflect the composed (not the bare) shock."""

    async def fake_permissions(_user, _state):
        return {"portfolio.view"}

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    agent = ChatAgent(llm=MockLLMProvider())

    result = await agent.ask(
        "What happens if Freeport LNG goes offline and prices spike 20%?", _scenario_capable_fake_state(), user
    )

    assert result.access_granted is True
    assert result.tool_used == "run_named_scenario"
    assert result.permission_required == "portfolio.view"
    assert "+20%" in result.content


async def test_run_named_scenario_without_percentage_is_unchanged(monkeypatch, user):
    async def fake_permissions(_user, _state):
        return {"portfolio.view"}

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    agent = ChatAgent(llm=MockLLMProvider())

    result = await agent.ask("Run a scenario where Freeport LNG goes offline", _scenario_capable_fake_state(), user)

    assert result.tool_used == "run_named_scenario"
    assert "Freeport" in result.content or "LNG" in result.content
    assert "%" not in result.content.split(":")[0]  # no composed-shock note in the scenario name clause


async def test_scenario_comparison_routes_and_reads_the_standing_library(monkeypatch, user):
    async def fake_permissions(_user, _state):
        return {"alpha_scenarios.view"}

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    agent = ChatAgent(llm=MockLLMProvider())

    result = await agent.ask(
        "Can you compare scenarios across my whole book?", _scenario_capable_fake_state(), user
    )

    assert result.access_granted is True
    assert result.tool_used == "scenario_comparison"
    assert result.permission_required == "alpha_scenarios.view"
    assert "14 scenarios" in result.content
    assert "Worst case" in result.content


async def test_scenario_comparison_declined_without_permission(monkeypatch, user):
    async def fake_permissions(_user, _state):
        return set()

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    agent = ChatAgent(llm=MockLLMProvider())

    # _FakeState has no `alpha_scenario_engine`/`paper_adapter` -- a wrongly-dispatched
    # tool call would raise AttributeError instead of returning a declined result.
    result = await agent.ask("Stress test my portfolio against every scenario", _FakeState(), user)

    assert result.access_granted is False
    assert result.tool_used == "scenario_comparison"
    assert "alpha_scenarios.view" in result.content


async def test_decision_memory_routes_to_alphamemory_tool(monkeypatch, user):
    """AlphaMemoryTool (docs/alpha-intelligence.md section 43/8): "what have we
    learned"/"lesson"/"decision memory" phrasing routes to the new topic, requires
    `alpha_memory.view`, and reads `state.recent_memory_records`/
    `recent_lesson_proposals`."""
    from alpha_service import MemoryBuilder
    from schemas import (
        Direction,
        InstrumentType,
        InvestmentCommitteeDecision,
        OutcomeQuadrant,
        PostTradeAnalysis,
        RecommendedAction,
        RiskCheckResult,
        RiskVerdict,
        TradeIdea,
    )

    async def fake_permissions(_user, _state):
        return {"alpha_memory.view"}

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    agent = ChatAgent(llm=MockLLMProvider())

    trade = TradeIdea(
        strategy="DIRECTIONAL",
        instrument="NG_M1",
        instrument_type=InstrumentType.FUTURE,
        direction=Direction.LONG,
        entry=3.0,
        target=3.5,
        stop_or_invalidation=2.8,
        time_horizon="1W",
        expected_return=0.5,
        expected_loss=0.2,
        probability_success=0.6,
        confidence=0.7,
        thesis="cold winter",
    )
    committee = InvestmentCommitteeDecision(
        original_trade=trade,
        bull_case="b",
        bear_case="c",
        skeptic_case="d",
        data_quality_assessment="ok",
        portfolio_effect="ok",
        consensus_score=0.8,
        recommended_action=RecommendedAction.APPROVE_FOR_REVIEW,
    )
    risk_check = RiskCheckResult(trade_id=trade.trade_id, verdict=RiskVerdict.ALLOW, rule_results=[], governor_version="1.0")
    post_trade = PostTradeAnalysis(
        trade_id=trade.trade_id,
        thesis_accuracy=0.9,
        timing_accuracy=1.0,
        risk_accuracy=1.0,
        lessons="Thesis was directionally correct.",
        quadrant=OutcomeQuadrant.GOOD_DECISION_GOOD_OUTCOME,
    )
    memory = MemoryBuilder().build_decision_memory(
        trade=trade, committee=committee, risk_check=risk_check, post_trade=post_trade
    )
    state = _FakeState()
    state.recent_memory_records = [memory]
    state.recent_lesson_proposals = []

    result = await agent.ask("What have we learned from past trades?", state, user)

    assert result.access_granted is True
    assert result.tool_used == "decision_memory"
    assert result.permission_required == "alpha_memory.view"
    assert "GOOD_DECISION_GOOD_OUTCOME" in result.content


async def test_decision_memory_declined_without_permission(monkeypatch, user):
    async def fake_permissions(_user, _state):
        return set()

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    agent = ChatAgent(llm=MockLLMProvider())

    # _FakeState has no `recent_memory_records` attribute -- a wrongly-dispatched
    # tool call would raise AttributeError instead of returning a declined result.
    result = await agent.ask("Any lessons from recent decisions?", _FakeState(), user)

    assert result.access_granted is False
    assert result.tool_used == "decision_memory"
    assert "alpha_memory.view" in result.content


async def test_replay_snapshot_routes_to_alphareplay_tool(monkeypatch, user):
    """AlphaReplayTool (docs/alpha-intelligence.md section 43/9): "time machine"/
    "as of"/"what did we know" phrasing routes to the new topic, requires
    `alpha_replay.view`, and awaits `state.compute_as_of_replay()` directly --
    this is the one Alpha* topic that cannot be answered from a bounded
    in-memory cache, so `_dispatch` itself had to become `async def`."""
    from datetime import datetime, timezone

    from schemas import AsOfReplayResult, ReplayMode

    async def fake_permissions(_user, _state):
        return {"alpha_replay.view"}

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    agent = ChatAgent(llm=MockLLMProvider())

    captured = {}

    class _ReplayState(_FakeState):
        async def compute_as_of_replay(self, *, as_of, organization_id=None, market=None):
            captured["as_of"] = as_of
            return AsOfReplayResult(as_of=as_of, mode=ReplayMode.CURRENT_MODEL_RETROSPECTIVE)

    result = await agent.ask("What did we know as of 2024-01-15?", _ReplayState(), user)

    assert result.access_granted is True
    assert result.tool_used == "replay_snapshot"
    assert result.permission_required == "alpha_replay.view"
    assert "CURRENT_MODEL_RETROSPECTIVE" in result.content
    assert captured["as_of"] == datetime(2024, 1, 15, tzinfo=timezone.utc)


async def test_replay_snapshot_declined_without_permission(monkeypatch, user):
    async def fake_permissions(_user, _state):
        return set()

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    agent = ChatAgent(llm=MockLLMProvider())

    # _FakeState has no `compute_as_of_replay` method -- a wrongly-dispatched tool
    # call would raise AttributeError instead of returning a declined result.
    result = await agent.ask("Use the AlphaReplay time machine", _FakeState(), user)

    assert result.access_granted is False
    assert result.tool_used == "replay_snapshot"
    assert "alpha_replay.view" in result.content


async def test_overnight_brief_routes_to_the_brief_tool(monkeypatch, user):
    """Milestone 7 (docs/alpha-intelligence.md section 10): "overnight brief"/
    "morning brief"/"daily brief"/"intelligence brief" phrasing routes to the new
    topic, requires `alpha_brief.view`, and reads `state.recent_briefs` -- the
    same bounded in-memory cache pattern every non-AlphaReplay Alpha* topic uses."""
    from schemas import IntelligenceBrief

    async def fake_permissions(_user, _state):
        return {"alpha_brief.view"}

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    agent = ChatAgent(llm=MockLLMProvider())

    from datetime import datetime, timezone

    brief = IntelligenceBrief(
        period_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        period_end=datetime(2026, 1, 2, tzinfo=timezone.utc),
        headline="Cold snap driving bullish signals",
        summary="2 material signal(s) detected.",
    )
    state = _FakeState()
    state.recent_briefs = [brief]

    result = await agent.ask("Give me the overnight brief", state, user)

    assert result.access_granted is True
    assert result.tool_used == "overnight_brief"
    assert result.permission_required == "alpha_brief.view"
    assert "Cold snap driving bullish signals" in result.content


async def test_overnight_brief_declined_without_permission(monkeypatch, user):
    async def fake_permissions(_user, _state):
        return set()

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    agent = ChatAgent(llm=MockLLMProvider())

    # _FakeState has no `recent_briefs` attribute -- a wrongly-dispatched tool
    # call would raise AttributeError instead of returning a declined result.
    result = await agent.ask("What's in the morning brief?", _FakeState(), user)

    assert result.access_granted is False
    assert result.tool_used == "overnight_brief"
    assert "alpha_brief.view" in result.content


class _FakeEnterpriseRepo:
    """Minimal stand-in for `Repository`'s enterprise-data read methods used by
    `ChatAgent._enterprise_data_query` -- returns whatever dataset/policy/entitlement
    dicts a test sets up, without a real database. `entitlements`/`workspace_ids`
    default to empty, matching the real repo's behavior for a dataset nobody has
    ever entitled (visible to the whole organization -- see `dataset_is_entitled`'s
    docstring) and a user in no workspace, so every existing test that doesn't set
    these up keeps seeing every dataset exactly as before."""

    def __init__(self, *, datasets=None, policies=None, entitlements=None, workspace_ids=None):
        self.datasets = datasets or []
        self.policies = policies or []
        self.entitlements = entitlements or {}
        self.workspace_ids = workspace_ids or []

    async def list_enterprise_datasets(self, *, organization_id):
        return [d for d in self.datasets if d["organization_id"] == organization_id]

    async def list_model_routing_policies(self, *, organization_id):
        return [p for p in self.policies if p["organization_id"] in (organization_id, None)]

    async def list_enterprise_data_entitlements(self, dataset_id):
        return self.entitlements.get(dataset_id, [])

    async def list_workspace_ids_for_user(self, user_id):
        return self.workspace_ids


class _EnterpriseDataState(_FakeState):
    def __init__(self, *, datasets=None, policies=None, entitlements=None, workspace_ids=None):
        super().__init__()
        from enterprise_data_service import ModelRoutingEngine

        self.repo = _FakeEnterpriseRepo(
            datasets=datasets, policies=policies, entitlements=entitlements, workspace_ids=workspace_ids
        )
        self.model_routing_engine = ModelRoutingEngine()


async def test_enterprise_data_query_routes_and_requires_permission(monkeypatch, user):
    async def fake_permissions(_user, _state):
        return set()

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    agent = ChatAgent(llm=MockLLMProvider())

    # _FakeState has no `repo` attribute -- a wrongly-dispatched tool call would
    # raise AttributeError instead of returning a declined result.
    result = await agent.ask("What is in my enterprise data?", _FakeState(), user)

    assert result.access_granted is False
    assert result.tool_used == "enterprise_data_query"
    assert "enterprise_data.query" in result.content


async def test_enterprise_data_query_declines_when_org_unresolvable(monkeypatch, user):
    async def fake_permissions(_user, _state):
        return {"enterprise_data.query"}

    async def fake_resolve(_user, _state):
        return None

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    monkeypatch.setattr(chat_agent_module, "resolve_organization_id", fake_resolve)
    agent = ChatAgent(llm=MockLLMProvider())

    result = await agent.ask("What is in my enterprise data?", _EnterpriseDataState(), user)

    assert result.access_granted is True
    assert result.tool_used == "enterprise_data_query"
    assert "can't identify your organization" in result.content


async def test_enterprise_data_query_withholds_data_blocked_by_routing_policy(monkeypatch, user):
    """The core Milestone 10 integration: a `CUSTOMER_RESTRICTED` dataset with no
    `ModelRoutingPolicy` override defaults to blocked (Milestone 9's
    `ModelRoutingEngine`), so its content is named but withheld -- never
    silently included in the facts handed to the LLM."""

    async def fake_permissions(_user, _state):
        return {"enterprise_data.query"}

    async def fake_resolve(_user, _state):
        return "org-a"

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    monkeypatch.setattr(chat_agent_module, "resolve_organization_id", fake_resolve)
    agent = ChatAgent(llm=MockLLMProvider())

    state = _EnterpriseDataState(
        datasets=[
            {
                "id": "ds-1",
                "organization_id": "org-a",
                "name": "positions",
                "domain": "POSITION",
                "classification": "CUSTOMER_RESTRICTED",
                "row_count": 5,
            },
            {
                "id": "ds-2",
                "organization_id": "org-a",
                "name": "wells",
                "domain": "ASSET",
                "classification": "PUBLIC",
                "row_count": 3,
            },
        ],
        policies=[],
    )

    result = await agent.ask("What is in my enterprise data?", state, user)

    assert result.access_granted is True
    assert result.tool_used == "enterprise_data_query"
    assert "withheld" in result.content
    assert "positions" in result.content
    assert "wells" in result.content
    assert result.freshness == {"dataset_count": 2, "withheld_count": 1}


async def test_enterprise_data_query_hides_dataset_with_non_matching_entitlement(monkeypatch, user):
    """#3: fine-grained per-dataset `EnterpriseDataEntitlement` enforcement. A
    dataset that has an entitlement grant at all switches to allow-list mode -- a
    caller not matching any grant no longer sees it, even though it's their own
    organization's dataset."""

    async def fake_permissions(_user, _state):
        return {"enterprise_data.query"}

    async def fake_resolve(_user, _state):
        return "org-a"

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    monkeypatch.setattr(chat_agent_module, "resolve_organization_id", fake_resolve)
    agent = ChatAgent(llm=MockLLMProvider())

    state = _EnterpriseDataState(
        datasets=[
            {
                "id": "ds-1",
                "organization_id": "org-a",
                "name": "wells",
                "domain": "ASSET",
                "classification": "PUBLIC",
                "row_count": 3,
            }
        ],
        policies=[],
        entitlements={"ds-1": [{"dataset_id": "00000000-0000-0000-0000-000000000001", "principal_type": "USER", "principal_id": "someone-else"}]},
    )

    result = await agent.ask("What is in my enterprise data?", state, user)

    assert result.access_granted is True
    assert "aren't entitled to any" in result.content


async def test_enterprise_data_query_shows_dataset_with_matching_user_entitlement(monkeypatch, user):
    async def fake_permissions(_user, _state):
        return {"enterprise_data.query"}

    async def fake_resolve(_user, _state):
        return "org-a"

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    monkeypatch.setattr(chat_agent_module, "resolve_organization_id", fake_resolve)
    agent = ChatAgent(llm=MockLLMProvider())

    state = _EnterpriseDataState(
        datasets=[
            {
                "id": "ds-1",
                "organization_id": "org-a",
                "name": "wells",
                "domain": "ASSET",
                "classification": "PUBLIC",
                "row_count": 3,
            }
        ],
        policies=[],
        entitlements={"ds-1": [{"dataset_id": "00000000-0000-0000-0000-000000000001", "principal_type": "USER", "principal_id": user.user_id}]},
    )

    result = await agent.ask("What is in my enterprise data?", state, user)

    assert result.access_granted is True
    assert "wells" in result.content


async def test_enterprise_data_query_shows_dataset_with_matching_role_entitlement(monkeypatch, user):
    async def fake_permissions(_user, _state):
        return {"enterprise_data.query"}

    async def fake_resolve(_user, _state):
        return "org-a"

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    monkeypatch.setattr(chat_agent_module, "resolve_organization_id", fake_resolve)
    agent = ChatAgent(llm=MockLLMProvider())

    state = _EnterpriseDataState(
        datasets=[
            {
                "id": "ds-1",
                "organization_id": "org-a",
                "name": "wells",
                "domain": "ASSET",
                "classification": "PUBLIC",
                "row_count": 3,
            }
        ],
        policies=[],
        entitlements={"ds-1": [{"dataset_id": "00000000-0000-0000-0000-000000000001", "principal_type": "ROLE", "principal_id": user.roles[0].value}]},
    )

    result = await agent.ask("What is in my enterprise data?", state, user)

    assert result.access_granted is True
    assert "wells" in result.content


async def test_enterprise_data_query_shows_dataset_with_matching_workspace_entitlement(monkeypatch, user):
    async def fake_permissions(_user, _state):
        return {"enterprise_data.query"}

    async def fake_resolve(_user, _state):
        return "org-a"

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    monkeypatch.setattr(chat_agent_module, "resolve_organization_id", fake_resolve)
    agent = ChatAgent(llm=MockLLMProvider())

    state = _EnterpriseDataState(
        datasets=[
            {
                "id": "ds-1",
                "organization_id": "org-a",
                "name": "wells",
                "domain": "ASSET",
                "classification": "PUBLIC",
                "row_count": 3,
            }
        ],
        policies=[],
        entitlements={"ds-1": [{"dataset_id": "00000000-0000-0000-0000-000000000001", "principal_type": "WORKSPACE", "principal_id": "ws-1"}]},
        workspace_ids=["ws-1"],
    )

    result = await agent.ask("What is in my enterprise data?", state, user)

    assert result.access_granted is True
    assert "wells" in result.content


class _TaggedLLMProvider(MockLLMProvider):
    """Distinct `model` string from vanilla `MockLLMProvider`'s fixed
    `"mock-llm-deterministic"`, so a test can tell whether `PolicyGatedLLMProvider`
    routed to this instance (passed in as `self.llm`, i.e. `primary`) or to the
    fresh vanilla `MockLLMProvider()` `_enterprise_data_query` constructs as
    `fallback`."""

    def __init__(self, tag: str) -> None:
        self.model = tag


async def test_enterprise_data_query_routes_synthesis_through_primary_when_allowed(monkeypatch, user):
    """#6: `PolicyGatedLLMProvider` has a real live caller now -- when every involved
    dataset's classification allows external LLM processing, the final prose-synthesis
    call in `ask()` is routed to the primary (real) provider."""

    async def fake_permissions(_user, _state):
        return {"enterprise_data.query"}

    async def fake_resolve(_user, _state):
        return "org-a"

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    monkeypatch.setattr(chat_agent_module, "resolve_organization_id", fake_resolve)
    agent = ChatAgent(llm=_TaggedLLMProvider("primary-tag"))

    state = _EnterpriseDataState(
        datasets=[
            {
                "id": "ds-1",
                "organization_id": "org-a",
                "name": "wells",
                "domain": "ASSET",
                "classification": "PUBLIC",
                "row_count": 3,
            }
        ],
        policies=[],
    )

    result = await agent.ask("What is in my enterprise data?", state, user)

    assert result.model == "primary-tag"


async def test_enterprise_data_query_routes_synthesis_through_fallback_when_any_dataset_blocked(
    monkeypatch, user
):
    """The mirror case: one blocked dataset among several is enough to keep the whole
    synthesis call off the primary (real) provider -- most-restrictive-wins, same as the
    per-dataset content withholding already does."""

    async def fake_permissions(_user, _state):
        return {"enterprise_data.query"}

    async def fake_resolve(_user, _state):
        return "org-a"

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    monkeypatch.setattr(chat_agent_module, "resolve_organization_id", fake_resolve)
    agent = ChatAgent(llm=_TaggedLLMProvider("primary-tag"))

    state = _EnterpriseDataState(
        datasets=[
            {
                "id": "ds-1",
                "organization_id": "org-a",
                "name": "positions",
                "domain": "POSITION",
                "classification": "CUSTOMER_RESTRICTED",
                "row_count": 5,
            },
            {
                "id": "ds-2",
                "organization_id": "org-a",
                "name": "wells",
                "domain": "ASSET",
                "classification": "PUBLIC",
                "row_count": 3,
            },
        ],
        policies=[],
    )

    result = await agent.ask("What is in my enterprise data?", state, user)

    assert result.model != "primary-tag"
    assert result.model == MockLLMProvider().model


async def test_enterprise_data_query_includes_data_allowed_by_org_override(monkeypatch, user):
    async def fake_permissions(_user, _state):
        return {"enterprise_data.query"}

    async def fake_resolve(_user, _state):
        return "org-a"

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    monkeypatch.setattr(chat_agent_module, "resolve_organization_id", fake_resolve)
    agent = ChatAgent(llm=MockLLMProvider())

    state = _EnterpriseDataState(
        datasets=[
            {
                "id": "ds-1",
                "organization_id": "org-a",
                "name": "positions",
                "domain": "POSITION",
                "classification": "CUSTOMER_RESTRICTED",
                "row_count": 5,
            }
        ],
        policies=[
            {
                "organization_id": "org-a",
                "data_classification": "CUSTOMER_RESTRICTED",
                "allow_external_llm_processing": True,
                "allowed_provider": None,
                "allowed_region": None,
                "logging_allowed": True,
            }
        ],
    )

    result = await agent.ask("What is in my enterprise data?", state, user)

    assert result.access_granted is True
    assert "withheld" not in result.content
    assert result.freshness == {"dataset_count": 1, "withheld_count": 0}


class _EnterpriseTradeIdeaState(_FakeState):
    """Minimal stand-in for `ChatAgent._enterprise_trade_idea`'s dependency on
    `AppState.generate_enterprise_trade_idea` -- returns whatever `Approval` (or
    `None`, for the data-driven-SKIP case) a test configures, without running a
    real research cycle."""

    def __init__(self, *, approval=None, trade=None):
        super().__init__()
        self._approval = approval
        self.generate_enterprise_trade_idea_calls: list[str] = []
        if approval is not None and trade is not None:
            self.trade_ideas[approval.trade_id] = trade

    async def generate_enterprise_trade_idea(self, *, organization_id):
        self.generate_enterprise_trade_idea_calls.append(organization_id)
        return self._approval


def _make_enterprise_trade() -> "TradeIdea":
    from schemas import Direction, InstrumentType, TradeIdea

    return TradeIdea(
        strategy="TEST",
        organization_id="org-a",
        instrument="NG.FUT.M1",
        instrument_type=InstrumentType.FUTURE,
        direction=Direction.LONG,
        entry=3.0,
        target=3.5,
        stop_or_invalidation=2.8,
        time_horizon="1W",
        expected_return=0.5,
        expected_loss=0.2,
        probability_success=0.6,
        confidence=0.7,
        thesis="test thesis",
        catalysts=["cold snap"],
        risks=["storage build"],
    )


async def test_enterprise_trade_idea_routes_and_requires_permission(monkeypatch, user):
    async def fake_permissions(_user, _state):
        return set()

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    agent = ChatAgent(llm=MockLLMProvider())

    # _FakeState has no `generate_enterprise_trade_idea` -- a wrongly-dispatched
    # call would raise AttributeError instead of returning a declined result.
    result = await agent.ask("Generate a trade idea for our organization", _FakeState(), user)

    assert result.access_granted is False
    assert result.tool_used == "enterprise_trade_idea"
    assert "enterprise_trading.generate" in result.content


async def test_enterprise_trade_idea_declines_when_org_unresolvable(monkeypatch, user):
    async def fake_permissions(_user, _state):
        return {"enterprise_trading.generate"}

    async def fake_resolve(_user, _state):
        return None

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    monkeypatch.setattr(chat_agent_module, "resolve_organization_id", fake_resolve)
    agent = ChatAgent(llm=MockLLMProvider())

    result = await agent.ask(
        "Generate a trade idea for our organization", _EnterpriseTradeIdeaState(), user
    )

    assert result.access_granted is True
    assert result.tool_used == "enterprise_trade_idea"
    assert "can't identify your organization" in result.content


async def test_enterprise_trade_idea_reports_no_idea_on_data_driven_skip(monkeypatch, user):
    async def fake_permissions(_user, _state):
        return {"enterprise_trading.generate"}

    async def fake_resolve(_user, _state):
        return "org-a"

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    monkeypatch.setattr(chat_agent_module, "resolve_organization_id", fake_resolve)
    agent = ChatAgent(llm=MockLLMProvider())

    state = _EnterpriseTradeIdeaState(approval=None)
    result = await agent.ask("Generate a trade idea for our organization", state, user)

    assert result.access_granted is True
    assert state.generate_enterprise_trade_idea_calls == ["org-a"]
    assert "No trade idea right now" in result.content


async def test_enterprise_trade_idea_reports_the_generated_trade(monkeypatch, user):
    from api_app.models import Approval

    async def fake_permissions(_user, _state):
        return {"enterprise_trading.generate"}

    async def fake_resolve(_user, _state):
        return "org-a"

    monkeypatch.setattr(chat_agent_module, "get_effective_permissions", fake_permissions)
    monkeypatch.setattr(chat_agent_module, "resolve_organization_id", fake_resolve)
    agent = ChatAgent(llm=MockLLMProvider())

    trade = _make_enterprise_trade()
    approval = Approval(trade_id=trade.trade_id)
    state = _EnterpriseTradeIdeaState(approval=approval, trade=trade)

    result = await agent.ask("Generate a trade idea for our organization", state, user)

    assert result.access_granted is True
    assert "LONG" in result.content
    assert "cold snap" in result.content
    assert "storage build" in result.content
    assert result.freshness["organization_id"] == "org-a"
    assert result.freshness["trade_id"] == str(trade.trade_id)
