from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from schemas import ApprovalAction, ApprovalState


class ApprovalActionRecord(BaseModel):
    action: ApprovalAction
    payload: dict[str, Any] = Field(default_factory=dict)
    user_id: str
    at: datetime = Field(default_factory=datetime.utcnow)


class Approval(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    trade_id: UUID
    state: ApprovalState = ApprovalState.DRAFT
    actions: list[ApprovalActionRecord] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    freshness: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ChatSession(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: str
    messages: list[ChatMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
