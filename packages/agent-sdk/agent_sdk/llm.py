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


def get_default_llm_provider() -> LLMProvider:
    """Factory used across services: returns a real Anthropic-backed provider when
    ANTHROPIC_API_KEY is set, otherwise the deterministic mock."""
    import os

    if os.environ.get("ANTHROPIC_API_KEY"):
        from .anthropic_provider import AnthropicLLMProvider

        return AnthropicLLMProvider()
    return MockLLMProvider()
