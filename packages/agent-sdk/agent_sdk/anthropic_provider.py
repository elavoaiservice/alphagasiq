from __future__ import annotations

import os
from typing import Any

from .llm import LLMMessage, LLMProvider, LLMResponse

DEFAULT_MODEL = "claude-sonnet-5"


class AnthropicLLMProvider(LLMProvider):
    """Real Claude-backed provider, used whenever ANTHROPIC_API_KEY is configured.

    Imports the `anthropic` SDK lazily so the rest of the platform (including all
    tests) never requires it to be installed.
    """

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None):
        self.model = model
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> LLMResponse:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self._api_key)
        kwargs: dict[str, Any] = dict(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": m.role, "content": m.content} for m in messages if m.role != "system"],
        )
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools

        resp = await client.messages.create(**kwargs)
        text_parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        tool_calls = [
            b.model_dump() for b in resp.content if getattr(b, "type", None) == "tool_use"
        ]
        return LLMResponse(
            content="".join(text_parts),
            model=resp.model,
            stop_reason=resp.stop_reason,
            tool_calls=tool_calls,
            usage={
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
            },
        )
