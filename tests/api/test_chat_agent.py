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
