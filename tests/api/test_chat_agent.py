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
