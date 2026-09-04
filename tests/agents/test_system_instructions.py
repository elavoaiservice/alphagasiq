"""#1: agent versioning -> live execution (docs/agent-governance.md §4).

Covers the `agent_sdk` primitives that make a PRODUCTION `AgentVersionRow` actually
change what a live agent does: `BaseAgent.system_instructions`, `MockLLMProvider`'s
`model` override, and the `build_llm_provider()` factory. The API-level proof that a
version promotion applies these to a real running agent lives in
`tests/api/test_admin_agent_versions.py`."""

from __future__ import annotations

import pytest
from agent_sdk import LLMMessage, LLMProvider, LLMResponse, MockLLMProvider, build_llm_provider
from agents_service import SupplyAgent
from fundamentals_service.seed import generate_daily_balances
from datetime import date


class _RecordingLLMProvider(LLMProvider):
    """Captures the `system` kwarg every `complete()` call receives, so tests can
    assert an agent forwarded its `system_instructions` rather than dropping it."""

    model = "recording-provider"

    def __init__(self) -> None:
        self.received_system: list[str | None] = []

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        tools=None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> LLMResponse:
        self.received_system.append(system)
        return LLMResponse(content="ok", model=self.model, stop_reason="end_turn")


def test_mock_llm_provider_defaults_to_class_model():
    assert MockLLMProvider().model == "mock-llm-deterministic"


def test_mock_llm_provider_accepts_model_override():
    assert MockLLMProvider(model="claude-sonnet-5").model == "claude-sonnet-5"


def test_build_llm_provider_without_api_key_pins_mock_model(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = build_llm_provider("claude-opus-5")
    assert isinstance(provider, MockLLMProvider)
    assert provider.model == "claude-opus-5"


def test_build_llm_provider_with_api_key_pins_anthropic_model(monkeypatch):
    from agent_sdk.anthropic_provider import AnthropicLLMProvider

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    provider = build_llm_provider("claude-opus-5")
    assert isinstance(provider, AnthropicLLMProvider)
    assert provider.model == "claude-opus-5"


def test_base_agent_defaults_system_instructions_to_none():
    agent = SupplyAgent(llm=MockLLMProvider())
    assert agent.system_instructions is None


@pytest.mark.asyncio
async def test_agent_forwards_system_instructions_to_llm_complete():
    recorder = _RecordingLLMProvider()
    agent = SupplyAgent(llm=recorder)
    agent.system_instructions = "Be terse and cite EIA figures explicitly."
    balances = generate_daily_balances(end_date=date(2026, 8, 25), num_days=60)

    await agent.run(balances=balances)

    assert recorder.received_system == ["Be terse and cite EIA figures explicitly."]


@pytest.mark.asyncio
async def test_agent_forwards_none_system_instructions_by_default():
    recorder = _RecordingLLMProvider()
    agent = SupplyAgent(llm=recorder)
    balances = generate_daily_balances(end_date=date(2026, 8, 25), num_days=60)

    await agent.run(balances=balances)

    assert recorder.received_system == [None]
