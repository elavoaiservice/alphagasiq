"""Milestone 7: data-feed administration + health + dependency mapping (spec §§35-37).

`DataFeedConfigRow` deliberately carries no credential/secret field -- every
provider's API key is environment-provisioned via `packages/config/config/settings.py`
and never touches the DB or this admin surface, which is the strongest possible
reading of the spec's "credentials must never be redisplayed after entry." Every
endpoint here is gated by `admin.data_feeds` (granted to ADMIN and SUPER_ADMIN).
"""

from __future__ import annotations

import time

from data_sdk.provider import FetchRequest
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..auth import User
from ..data_feed_dependencies import full_dependency_map, get_dependencies
from ..deps import AppStateDep
from ..entitlements import require_permission

router = APIRouter(prefix="/admin/data-feeds", tags=["admin"])

_RequireDataFeeds = Depends(require_permission("admin.data_feeds"))


def _get_provider(state: AppStateDep, provider_id: str):
    """`ProviderRegistry.get` raises `KeyError` for an unregistered id (e.g. a config
    row left over after a provider was deregistered) -- callers here always want
    `None` instead, since a de-registered feed still has an admin-visible config row."""
    try:
        return state.providers.get(provider_id)
    except KeyError:
        return None


def _merge_provider_view(state: AppStateDep, provider_id: str, health, config: dict) -> dict:
    provider = _get_provider(state, provider_id)
    dependencies = get_dependencies(provider_id)
    return {
        "provider_id": provider_id,
        "source_type": provider.classification if provider is not None else None,
        "environment": state.settings.environment,
        "connection_status": health.status if health is not None else "unknown",
        "detail": health.detail if health is not None else "",
        "last_checked_at": health.checked_at if health is not None else None,
        "freshness_seconds": health.freshness_seconds if health is not None else None,
        "freshness_sla_seconds": provider.freshness_sla_seconds if provider is not None else None,
        "data_quality_score": None,
        "enabled": config["enabled"],
        "paused": config["paused"],
        "polling_frequency_seconds": config["polling_frequency_seconds"],
        "freshness_threshold_seconds": config["freshness_threshold_seconds"],
        "priority": config["priority"],
        "fallback_provider_id": config["fallback_provider_id"],
        "notes": config["notes"],
        "updated_by": config["updated_by"],
        "updated_at": config["updated_at"],
        "affected_agents": dependencies["affected_agents"],
        "affected_business_functions": dependencies["affected_business_functions"],
        "dependency_chain": dependencies["chain"],
    }


@router.get("")
async def list_data_feeds(state: AppStateDep, _admin: User = _RequireDataFeeds) -> list[dict]:
    health_by_provider = {h.provider_id: h for h in await state.providers.health_snapshot()}
    configs = await state.repo.list_data_feed_configs()
    return [
        _merge_provider_view(state, config["provider_id"], health_by_provider.get(config["provider_id"]), config)
        for config in configs
    ]


@router.get("/dependency-map")
async def dependency_map(_admin: User = _RequireDataFeeds) -> dict:
    return full_dependency_map()


@router.get("/{provider_id}")
async def get_data_feed(provider_id: str, state: AppStateDep, _admin: User = _RequireDataFeeds) -> dict:
    config = await state.repo.get_data_feed_config(provider_id)
    if config is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown data feed provider")
    provider = _get_provider(state, provider_id)
    health = await provider.health_check() if provider is not None else None
    return _merge_provider_view(state, provider_id, health, config)


class DataFeedUpdateRequest(BaseModel):
    enabled: bool | None = None
    paused: bool | None = None
    polling_frequency_seconds: int | None = None
    freshness_threshold_seconds: int | None = None
    priority: int | None = None
    fallback_provider_id: str | None = None
    notes: str | None = None


@router.patch("/{provider_id}")
async def update_data_feed(
    provider_id: str, body: DataFeedUpdateRequest, state: AppStateDep, admin: User = _RequireDataFeeds
) -> dict:
    if await state.repo.get_data_feed_config(provider_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown data feed provider")
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    fields["updated_by"] = admin.user_id
    config = await state.repo.update_data_feed_config(provider_id, **fields)
    provider = _get_provider(state, provider_id)
    health = await provider.health_check() if provider is not None else None
    return _merge_provider_view(state, provider_id, health, config)


@router.post("/{provider_id}/test-connection")
async def test_connection(provider_id: str, state: AppStateDep, _admin: User = _RequireDataFeeds) -> dict:
    if await state.repo.get_data_feed_config(provider_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown data feed provider")
    provider = _get_provider(state, provider_id)
    if provider is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not registered")
    started = time.monotonic()
    try:
        health = await provider.health_check()
        latency_ms = (time.monotonic() - started) * 1000
        event_status = "success" if health.status == "healthy" else "error"
        return await state.repo.record_data_feed_event(
            provider_id=provider_id,
            event_type="test_connection",
            status=event_status,
            detail=health.detail,
            latency_ms=latency_ms,
        )
    except Exception as exc:  # noqa: BLE001 - feed failures are expected/normal, never a 500
        latency_ms = (time.monotonic() - started) * 1000
        return await state.repo.record_data_feed_event(
            provider_id=provider_id,
            event_type="test_connection",
            status="error",
            detail=str(exc),
            latency_ms=latency_ms,
        )


@router.post("/{provider_id}/refresh")
async def manual_refresh(provider_id: str, state: AppStateDep, _admin: User = _RequireDataFeeds) -> dict:
    if await state.repo.get_data_feed_config(provider_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown data feed provider")
    provider = _get_provider(state, provider_id)
    if provider is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not registered")
    started = time.monotonic()
    try:
        observations = await provider.fetch(FetchRequest())
        latency_ms = (time.monotonic() - started) * 1000
        return await state.repo.record_data_feed_event(
            provider_id=provider_id,
            event_type="manual_refresh",
            status="success",
            detail=f"Fetched {len(observations)} observation(s).",
            records_received=len(observations),
            latency_ms=latency_ms,
        )
    except Exception as exc:  # noqa: BLE001 - feed failures are expected/normal, never a 500
        latency_ms = (time.monotonic() - started) * 1000
        return await state.repo.record_data_feed_event(
            provider_id=provider_id,
            event_type="manual_refresh",
            status="error",
            detail=str(exc),
            latency_ms=latency_ms,
        )


@router.get("/{provider_id}/events")
async def list_events(provider_id: str, state: AppStateDep, _admin: User = _RequireDataFeeds) -> list[dict]:
    if await state.repo.get_data_feed_config(provider_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown data feed provider")
    return await state.repo.list_data_feed_events(provider_id)
