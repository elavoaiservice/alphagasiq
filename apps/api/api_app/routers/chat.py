from __future__ import annotations

from uuid import UUID

from agent_sdk import get_default_llm_provider
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import User, get_optional_user
from ..chat_agent import ChatAgent
from ..deps import AppStateDep
from ..models import ChatMessage, ChatSession

router = APIRouter(prefix="/chat", tags=["chat"])

_chat_agent = ChatAgent(llm=get_default_llm_provider())


@router.post("/sessions", response_model=ChatSession)
async def create_session(state: AppStateDep, user: User = Depends(get_optional_user)):
    session = ChatSession(user_id=user.user_id)
    state.chat_sessions[session.id] = session
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
async def send_message(session_id: UUID, body: SendMessageRequest, state: AppStateDep):
    session = state.chat_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Chat session not found")

    user_message = ChatMessage(role="user", content=body.content)
    session.messages.append(user_message)

    result = await _chat_agent.ask(body.content, state)
    assistant_message = ChatMessage(
        role="assistant",
        content=result.content,
        citations=result.citations,
        freshness=result.freshness,
    )
    session.messages.append(assistant_message)
    return assistant_message
