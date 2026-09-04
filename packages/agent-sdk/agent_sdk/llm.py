from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel


class LLMMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class LLMResponse(BaseModel):
    content: str
    model: str
    stop_reason: str | None = None
    tool_calls: list[dict[str, Any]] = []
    usage: dict[str, int] = {}


class LLMProvider(ABC):
    """Abstraction over the LLM backend.

    Every agent talks to the LLM only through this interface (never the Anthropic SDK
    directly), so (a) the platform can run fully offline/deterministically in tests and
    demo mode via `MockLLMProvider`, and (b) the provider can be swapped without
    touching agent logic.
    """

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> LLMResponse: ...


class MockLLMProvider(LLMProvider):
    """Deterministic, network-free provider used in tests and whenever
    ANTHROPIC_API_KEY is not configured, so the platform is always demoable.

    It does not attempt to "look smart" — it echoes a templated, clearly-labeled
    synthetic response so it is never mistaken for a real model output.
    """

    model = "mock-llm-deterministic"

    def __init__(self, model: str | None = None) -> None:
        if model:
            self.model = model

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> LLMResponse:
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        content = (
            "[MOCK LLM RESPONSE — ANTHROPIC_API_KEY not configured] "
            f"Received prompt of {len(last_user)} chars. Configure ANTHROPIC_API_KEY to "
            "enable real Claude reasoning."
        )
        return LLMResponse(content=content, model=self.model, stop_reason="end_turn")


class PolicyGatedLLMProvider(LLMProvider):
    """Tenant-isolation retrofit (docs/alpha-intelligence.md section 11.1,
    Milestone 9): wraps a `primary` provider (typically an external one, e.g.
    `AnthropicLLMProvider`) and a `fallback` provider (typically a local/mock
    one), and consults a pre-resolved `RoutingDecision`
    (`enterprise_data_service.model_routing.ModelRoutingEngine.evaluate()`) to
    decide which one actually handles `complete()`. `decision.allowed=False`
    routes to `fallback` instead of `primary` -- e.g. so `CUSTOMER_RESTRICTED`
    content can be kept off an external LLM provider entirely when an
    organization's `ModelRoutingPolicy` says so.

    `apps/api/api_app/chat_agent.py`'s `ChatAgent._enterprise_data_query` is the live
    caller: it evaluates every enterprise dataset classification a chat request
    touches and wraps the final prose-synthesis `complete()` call in an instance of
    this class, gated by the combined decision across every involved dataset (blocked
    if any one of them is). No *agent* call site classifies the content it's about to
    send an LLM yet (see `model_routing.py`'s module docstring for why) -- that
    remains real follow-up work, honestly not claimed as done here."""

    def __init__(self, *, primary: LLMProvider, fallback: LLMProvider, decision: Any) -> None:
        """`decision` is an `enterprise_data_service.model_routing.RoutingDecision`
        (or anything duck-typed with an `.allowed: bool` attribute) -- typed as
        `Any` rather than imported, since `agent_sdk` is a lower-level package
        that `enterprise_data_service` depends on, not the reverse."""
        self._primary = primary
        self._fallback = fallback
        self._decision = decision

    @property
    def model(self) -> str:
        provider = self._primary if self._decision.allowed else self._fallback
        return getattr(provider, "model", provider.__class__.__name__)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> LLMResponse:
        provider = self._primary if self._decision.allowed else self._fallback
        return await provider.complete(
            messages, system=system, tools=tools, max_tokens=max_tokens, temperature=temperature
        )


def get_default_llm_provider() -> LLMProvider:
    """Factory used across services: returns a real Anthropic-backed provider when
    ANTHROPIC_API_KEY is set, otherwise the deterministic mock."""
    import os

    if os.environ.get("ANTHROPIC_API_KEY"):
        from .anthropic_provider import AnthropicLLMProvider

        return AnthropicLLMProvider()
    return MockLLMProvider()


def build_llm_provider(model: str) -> LLMProvider:
    """Like `get_default_llm_provider()` but pins a specific model, so a promoted
    `AgentVersionRow.model_name` (docs/agent-governance.md §4) actually changes which
    model the live agent talks to instead of only being recorded for history. Falls
    back to the deterministic mock (pinned to `model` for visibility in tests/logs)
    when no `ANTHROPIC_API_KEY` is configured, same as `get_default_llm_provider()`."""
    import os

    if os.environ.get("ANTHROPIC_API_KEY"):
        from .anthropic_provider import AnthropicLLMProvider

        return AnthropicLLMProvider(model=model)
    return MockLLMProvider(model=model)
