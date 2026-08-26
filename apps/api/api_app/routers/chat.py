from __future__ import annotations

from uuid import UUID

from agent_sdk import get_default_llm_provider
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import User, get_optional_user
from ..chat_agent import ChatAgent
from ..deps import AppStateDep
from ..entitlements import require_permission, resolve_organization_id
from ..models import ChatMessage, ChatSession

router = APIRouter(prefix="/chat", tags=["chat"])

_chat_agent = ChatAgent(llm=get_default_llm_provider())


@router.post("/sessions", response_model=ChatSession)
async def create_session(state: AppStateDep, user: User = Depends(get_optional_user)):
    """Starting a session is deliberately left open to anonymous exploration (an
    empty conversation exposes nothing) — the real enforcement point is
    `send_message` below, gated per-question by `ChatAgent.ask()` (spec §28)."""
    session = ChatSession(user_id=user.user_id)
    state.chat_sessions[session.id] = session
    organization_id = await resolve_organization_id(user, state)
    await state.repo.create_chat_conversation(
        conversation_id=str(session.id), user_id=user.user_id, organization_id=organization_id
    )
    return session


@router.get("/sessions/{session_id}", response_model=ChatSession)
async def get_session(session_id: UUID, state: AppStateDep):
    session = state.chat_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")
    return session


class SendMessageRequest(BaseModel):
    content: str


@router.post("/sessions/{session_id}/messages", response_model=ChatMessage)
async def send_message(
    session_id: UUID,
    body: SendMessageRequest,
    state: AppStateDep,
    user: User = Depends(require_permission("chief_agent.chat")),
):
    """Requires `chief_agent.chat` (spec §26: "Users with chief_agent.chat permission
    receive direct access to Chief Trading Agent") — an unauthenticated or
    unentitled caller is rejected here, before ever reaching `ChatAgent.ask()`. The
    per-topic permission check inside `ask()` is a second, narrower layer on top of
    this for roles that hold `chief_agent.chat` but not every underlying data
    permission (e.g. `portfolio.view`)."""
    session = state.chat_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")

    user_message = ChatMessage(role="user", content=body.content)
    session.messages.append(user_message)
    await state.repo.save_chat_message(conversation_id=str(session_id), role="user", content=body.content)

    result = await _chat_agent.ask(body.content, state, user)
    assistant_message = ChatMessage(
        role="assistant",
        content=result.content,
        citations=result.citations,
        freshness=result.freshness,
    )
    session.messages.append(assistant_message)
    await state.repo.save_chat_message(
        conversation_id=str(session_id),
        role="assistant",
        content=result.content,
        citations=result.citations,
        freshness=result.freshness,
        tool_used=result.tool_used,
        model=result.model,
        latency_ms=result.latency_ms,
        permissions_context={
            "roles": [r.value for r in user.roles],
            "permission_required": result.permission_required,
            "access_granted": result.access_granted,
        },
    )
    return assistant_message


@router.get("/conversations", dependencies=[Depends(require_permission("admin.audit_logs"))])
async def list_conversations(state: AppStateDep, user_id: str | None = None) -> list[dict]:
    """Admin visibility into chat usage metadata (spec §29). Gated by
    `admin.audit_logs` — the closest existing permission to "read platform activity
    records" until a dedicated one is warranted."""
    return await state.repo.list_chat_conversations(user_id=user_id)


@router.get("/conversations/{conversation_id}/messages", dependencies=[Depends(require_permission("admin.audit_logs"))])
async def list_conversation_messages(conversation_id: str, state: AppStateDep) -> list[dict]:
    if await state.repo.get_chat_conversation(conversation_id) is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return await state.repo.list_chat_messages(conversation_id)
