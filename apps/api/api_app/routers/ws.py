"""Gap-closure item #1 (docs/alpha-intelligence.md section 11.8): live push
updates. Every dashboard page today only fetches once on mount -- no polling,
no live feed. `GET /ws/events` is a single, reusable WebSocket endpoint that
forwards a fixed set of dashboard-relevant `DomainEvent`s (the same events
`AppState` already publishes to `state.event_bus` at every relevant mutation
site -- no new event plumbing needed, only a subscriber) to any connected
caller, filtered to what that caller is allowed to see.

A browser WebSocket handshake can't carry an `Authorization` header, so the
access token comes via `?token=` (the standard approach for FastAPI+JWT
WebSocket auth), decoded with the same `decode_access_token` REST endpoints
use. Visibility is enforced with the same `resolve_organization_scope` /
`record_is_visible` pair every Alpha* REST endpoint already uses -- a caller
only receives events whose payload's `organization_id` they could also read
via the REST API.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from schemas import DomainEvent, EventType

from ..auth import decode_access_token
from ..deps import AppStateDep
from ..entitlements import record_is_visible, resolve_organization_scope

router = APIRouter(tags=["websocket"])
logger = logging.getLogger("alphagasiq.ws")

# Dashboard-relevant event types (docs/architecture.md section 4's full `EventType`
# list also includes internal ingestion/forecast events no dashboard page renders
# directly -- forwarding those too would just be noise on every connection).
DASHBOARD_EVENT_TYPES = (
    # Market prices refresh on the worker's fast cadence (MARKET_REFRESH_SECONDS);
    # forwarding them is what makes the dashboard's price panels update live rather
    # than only on a page load.
    EventType.MARKET_PRICE_UPDATED,
    EventType.IMPACT_ANALYSIS_CREATED,
    EventType.CONSENSUS_UPDATED,
    EventType.SIGNAL_DETECTED,
    EventType.SIGNAL_ESCALATED,
    EventType.TRADE_IDEA_CREATED,
    EventType.TRADE_APPROVED,
    EventType.TRADE_REJECTED,
    EventType.RISK_LIMIT_BREACHED,
    EventType.OPPORTUNITY_PROPOSED,
    EventType.INTELLIGENCE_BRIEF_GENERATED,
    EventType.CONSENSUS_DIVERGENCE_DETECTED,
)


@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket, state: AppStateDep) -> None:
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401, reason="Missing token")
        return
    try:
        user = await decode_access_token(token, state)
    except HTTPException:
        await websocket.close(code=4401, reason="Invalid or expired token")
        return

    organization_id, unrestricted = await resolve_organization_scope(user, state)
    await websocket.accept()

    queue: asyncio.Queue[DomainEvent] = asyncio.Queue()

    async def _on_event(event: DomainEvent) -> None:
        await queue.put(event)

    for event_type in DASHBOARD_EVENT_TYPES:
        state.event_bus.subscribe(event_type.value, _on_event)

    try:
        while True:
            forward_task = asyncio.ensure_future(queue.get())
            receive_task = asyncio.ensure_future(websocket.receive())
            done, pending = await asyncio.wait({forward_task, receive_task}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()

            if receive_task in done:
                # A client message (or disconnect frame) arrived; this endpoint is
                # push-only, so the only thing we care about is whether the socket
                # closed -- raise so the disconnect is handled uniformly below.
                message = receive_task.result()
                if message.get("type") == "websocket.disconnect":
                    raise WebSocketDisconnect(message.get("code", 1000))
                continue

            event = forward_task.result()
            payload_organization_id = event.payload.get("organization_id")
            if not record_is_visible(payload_organization_id, organization_id, unrestricted):
                continue
            await websocket.send_json(
                {
                    "event_id": str(event.event_id),
                    "event_type": event.event_type.value,
                    "occurred_at": event.occurred_at.isoformat(),
                    "payload": event.payload,
                }
            )
    except WebSocketDisconnect:
        pass
    except Exception:  # pragma: no cover - defensive logging, matches InMemoryEventBus's handler guard
        logger.exception("WebSocket event stream failed for user %s", user.user_id)
    finally:
        for event_type in DASHBOARD_EVENT_TYPES:
            state.event_bus.unsubscribe(event_type.value, _on_event)
