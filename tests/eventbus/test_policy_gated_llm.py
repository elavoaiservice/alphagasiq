"""Tenant-isolation retrofit (docs/alpha-intelligence.md section 11.1, Milestone
9): `PolicyGatedLLMProvider` -- routes `complete()` to a primary (external) or
fallback (local) provider based on a pre-resolved routing decision."""

from __future__ import annotations

import pytest
from agent_sdk.llm import LLMMessage, MockLLMProvider, PolicyGatedLLMProvider


class _TaggedProvider(MockLLMProvider):
    def __init__(self, tag: str) -> None:
        self.model = tag


class _Decision:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed


@pytest.mark.asyncio
async def test_allowed_decision_routes_to_primary():
    primary = _TaggedProvider("primary")
    fallback = _TaggedProvider("fallback")
    gated = PolicyGatedLLMProvider(primary=primary, fallback=fallback, decision=_Decision(allowed=True))
    response = await gated.complete([LLMMessage(role="user", content="hi")])
    assert response.model == "primary"


@pytest.mark.asyncio
async def test_blocked_decision_routes_to_fallback():
    primary = _TaggedProvider("primary")
    fallback = _TaggedProvider("fallback")
    gated = PolicyGatedLLMProvider(primary=primary, fallback=fallback, decision=_Decision(allowed=False))
    response = await gated.complete([LLMMessage(role="user", content="hi")])
    assert response.model == "fallback"


def test_model_property_reflects_the_routed_provider():
    primary = _TaggedProvider("primary")
    fallback = _TaggedProvider("fallback")
    assert PolicyGatedLLMProvider(primary=primary, fallback=fallback, decision=_Decision(allowed=True)).model == "primary"
    assert PolicyGatedLLMProvider(primary=primary, fallback=fallback, decision=_Decision(allowed=False)).model == "fallback"
