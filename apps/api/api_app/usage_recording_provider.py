"""Wraps any LLMProvider and records token usage + cost after each completion,
so the admin Token Usage page can show spend. Fire-and-forget: recording never
blocks or breaks an agent call."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from agent_sdk import LLMMessage, LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class UsageRecordingLLMProvider(LLMProvider):
    def __init__(self, inner: LLMProvider, repo: Any, label: str | None = None) -> None:
        self._inner = inner
        self._repo = repo
        self._label = label

    def __getattr__(self, name: str) -> Any:
        # Transparent proxy: delegate anything we don't define (e.g. `.model`) to
        # the wrapped provider. (Only called when normal lookup fails, so the
        # instance attrs above and `complete` are unaffected.)
        if name in ("_inner", "_repo", "_label"):
            raise AttributeError(name)
        return getattr(self._inner, name)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> LLMResponse:
        resp = await self._inner.complete(
            messages, system=system, tools=tools, max_tokens=max_tokens, temperature=temperature
        )
        usage = resp.usage or {}
        it = int(usage.get("input_tokens") or 0)
        ot = int(usage.get("output_tokens") or 0)
        if it or ot:
            asyncio.create_task(self._record(resp.model, it, ot))
        return resp

    async def _record(self, model: str, it: int, ot: int) -> None:
        try:
            await self._repo.record_llm_usage(model, it, ot, self._label)
        except Exception:  # noqa: BLE001 — usage tracking must never affect the request
            logger.debug("llm usage recording failed", exc_info=True)
