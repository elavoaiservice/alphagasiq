from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .enums import AgentStatus, AgentType, DataClassification


class Citation(BaseModel):
    source: str
    reference: str = Field(description="URL, series id, or document id")
    publication_time: datetime | None = None
    classification: DataClassification = DataClassification.SIMULATED


class DataSourceRef(BaseModel):
    provider_id: str
    series_id: str | None = None
    classification: DataClassification


class AgentError(BaseModel):
    code: str
    message: str


class AgentResult(BaseModel):
    """The mandatory, auditable contract every agent execution must produce.

    No field carries private chain-of-thought — `reasoning_summary` is a concise,
    deliberately-written rationale (evidence, assumptions, model outputs, citations).
    """

    execution_id: UUID = Field(default_factory=uuid4)
    agent_id: str
    agent_name: str
    agent_type: AgentType
    version: str
    status: AgentStatus
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    tools: list[str] = Field(default_factory=list)
    data_sources: list[DataSourceRef] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    last_execution_time: datetime = Field(default_factory=datetime.utcnow)
    execution_duration_ms: float = 0.0
    reasoning_summary: str = ""
    citations: list[Citation] = Field(default_factory=list)
    errors: list[AgentError] = Field(default_factory=list)
