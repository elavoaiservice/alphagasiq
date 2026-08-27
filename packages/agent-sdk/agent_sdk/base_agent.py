from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from schemas import AgentError, AgentResult, AgentStatus, AgentType, Citation, DataSourceRef

from .llm import LLMProvider, MockLLMProvider


class BaseAgent(ABC):
    """Base class for every agent in the organization (docs/agents.md).

    Subclasses set the four identity class attributes and implement `_execute()`,
    which returns the agent-specific `outputs` payload plus reasoning/citations/data
    sources. `run()` wraps that call with timing, error handling, and construction of
    the mandatory `AgentResult` envelope — no subclass can accidentally omit a
    required field, and none can expose chain-of-thought since `_execute()` only ever
    returns the already-distilled `AgentOutcome`.
    """

    agent_id: str
    agent_name: str
    agent_type: AgentType
    version: str = "0.1.0"

    def __init__(self, llm: LLMProvider | None = None):
        self.llm = llm or MockLLMProvider()

    @abstractmethod
    async def _execute(self, **inputs: Any) -> "AgentOutcome": ...

    async def run(self, **inputs: Any) -> AgentResult:
        started = time.perf_counter()
        start_time = datetime.utcnow()
        try:
            outcome = await self._execute(**inputs)
            duration_ms = (time.perf_counter() - started) * 1000
            return AgentResult(
                agent_id=self.agent_id,
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                version=self.version,
                status=outcome.status,
                inputs={k: _safe_repr(v) for k, v in inputs.items()},
                outputs=outcome.outputs,
                tools=outcome.tools,
                data_sources=outcome.data_sources,
                confidence=outcome.confidence,
                last_execution_time=start_time,
                execution_duration_ms=duration_ms,
                reasoning_summary=outcome.reasoning_summary,
                citations=outcome.citations,
                errors=outcome.errors,
            )
        except Exception as exc:  # pragma: no cover - defensive envelope
            duration_ms = (time.perf_counter() - started) * 1000
            return AgentResult(
                agent_id=self.agent_id,
                agent_name=self.agent_name,
                agent_type=self.agent_type,
                version=self.version,
                status=AgentStatus.FAILED,
                inputs={k: _safe_repr(v) for k, v in inputs.items()},
                last_execution_time=start_time,
                execution_duration_ms=duration_ms,
                reasoning_summary="Agent execution raised an unhandled exception.",
                errors=[AgentError(code=type(exc).__name__, message=str(exc))],
            )

    def skipped_result(self, reason: str) -> AgentResult:
        """A well-formed `AgentResult` with `status=SKIPPED`, built without calling
        `_execute()` at all -- used by an orchestrator (`ChiefTradingAgent.
        run_research_cycle`, `InvestmentCommittee.deliberate`) when an administrator
        has disabled this agent (docs/agent-governance.md §3). Distinct from the
        `AgentOutcome(status=SKIPPED)` a subclass's own `_execute()` returns for a
        data-driven skip (e.g. no balances available) -- this one never runs the
        agent's logic at all."""
        return AgentResult(
            agent_id=self.agent_id,
            agent_name=self.agent_name,
            agent_type=self.agent_type,
            version=self.version,
            status=AgentStatus.SKIPPED,
            last_execution_time=datetime.utcnow(),
            execution_duration_ms=0.0,
            reasoning_summary=reason,
        )


class AgentOutcome:
    """What a concrete agent's `_execute()` returns — everything `run()` needs to
    build the mandatory `AgentResult`, without the subclass having to know about
    timing/versioning bookkeeping."""

    def __init__(
        self,
        *,
        outputs: dict[str, Any] | None = None,
        reasoning_summary: str = "",
        citations: list[Citation] | None = None,
        data_sources: list[DataSourceRef] | None = None,
        tools: list[str] | None = None,
        confidence: float | None = None,
        status: AgentStatus = AgentStatus.SUCCESS,
        errors: list[AgentError] | None = None,
    ):
        self.outputs = outputs or {}
        self.reasoning_summary = reasoning_summary
        self.citations = citations or []
        self.data_sources = data_sources or []
        self.tools = tools or []
        self.confidence = confidence
        self.status = status
        self.errors = errors or []


def _safe_repr(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return str(value)
