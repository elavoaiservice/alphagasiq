from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..deps import AppStateDep

router = APIRouter(prefix="/news", tags=["news"])


@router.get("/events")
async def events(state: AppStateDep, event_type: str | None = None, limit: int = 50):
    items = state.news_events
    if event_type:
        items = [e for e in items if e.event_type == event_type]
    return items[:limit]


@router.get("/events/{event_id}")
async def event_detail(event_id: str, state: AppStateDep):
    for e in state.news_events:
        if str(e.event_id) == event_id:
            return e
    raise HTTPException(status_code=404, detail="News event not found")
