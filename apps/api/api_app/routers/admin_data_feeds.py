"""Milestone 7: data-feed administration + health + dependency mapping (spec §§35-37).

`DataFeedConfigRow` deliberately carries no credential/secret field -- every
provider's API key is environment-provisioned via `packages/config/config/settings.py`
and never touches the DB or this admin surface, which is the strongest possible
reading of the spec's "credentials must never be redisplayed after entry." Every
endpoint here is gated by `admin.data_feeds` (granted to ADMIN and SUPER_ADMIN).
"""

from __future__ import annotations

import time

from data_sdk import compute_freshness_status
from data_sdk.provider import FetchRequest
from data_service.quality import DataQualityService
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..auth import User
from ..data_feed_dependencies import full_dependency_map, get_dependencies
from ..deps import AppStateDep
from .. import feed_scheduler
from ..entitlements import require_permission

_quality_service = DataQualityService()

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


async def _merge_provider_view(state: AppStateDep, provider_id: str, health, config: dict) -> dict:
    provider = _get_provider(state, provider_id)
    dependencies = get_dependencies(provider_id)
    last_ingestion = await state.repo.get_last_successful_ingestion(provider_id)
    freshness_status = compute_freshness_status(
        connection_status=health.status if health is not None else "not_configured",
        last_observation_time=last_ingestion["occurred_at"] if last_ingestion is not None else None,
        expected_update_frequency_seconds=config["freshness_threshold_seconds"]
        or (provider.freshness_sla_seconds if provider is not None else None),
    )
    return {
        "provider_id": provider_id,
        "source_type": provider.classification if provider is not None else None,
        # Licensing metadata (spec §31) -- `None` for a provider that hasn't
        # verified/declared its source's terms, never defaulted to permissive.
        "license_type": provider.license_type if provider is not None else None,
        "public_or_commercial": provider.public_or_commercial if provider is not None else None,
        "redistribution_allowed": provider.redistribution_allowed if provider is not None else None,
        "ai_processing_allowed": provider.ai_processing_allowed if provider is not None else None,
        "environment": state.settings.environment,
        "connection_status": health.status if health is not None else "unknown",
        "detail": health.detail if health is not None else "",
        "last_checked_at": health.checked_at if health is not None else None,
        "last_successful_ingestion_at": last_ingestion["occurred_at"] if last_ingestion is not None else None,
        "freshness_seconds": health.freshness_seconds if health is not None else None,
        "freshness_sla_seconds": provider.freshness_sla_seconds if provider is not None else None,
        "freshness_status": freshness_status,
        "data_quality_score": last_ingestion["avg_quality_score"] if last_ingestion is not None else None,
        "enabled": config["enabled"],
        "paused": config["paused"],
        "polling_frequency_seconds": config["polling_frequency_seconds"],
        # What the scheduler will actually do with this feed. `polling_frequency_seconds`
        # is the operator's setting and may be NULL; `effective_poll_seconds` is the
        # interval in force (the default for this provider when unset), `None` meaning
        # the feed is not scheduled at all — the honest stubs, which have nothing to
        # fetch. `poll_advisory` warns when a setting cannot deliver what it implies.
        "effective_poll_seconds": feed_scheduler.effective_interval(
            provider_id, config["polling_frequency_seconds"]
        ),
        "last_polled_at": config.get("last_polled_at"),
        "next_poll_due_at": feed_scheduler.next_due_at(config),
        "poll_advisory": feed_scheduler.advisory_for(provider_id, config["polling_frequency_seconds"]),
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
        await _merge_provider_view(state, config["provider_id"], health_by_provider.get(config["provider_id"]), config)
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
    return await _merge_provider_view(state, provider_id, health, config)


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
    return await _merge_provider_view(state, provider_id, health, config)


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
    # Route the result into the platform rather than fetching and discarding it.
    # This endpoint used to call `provider.fetch()` and throw the observations away,
    # logging "Fetched N observation(s)" while nothing on the dashboard changed --
    # the button reported success without refreshing anything.
    summary = await state.ingest_from_provider(provider_id)
    latency_ms = (time.monotonic() - started) * 1000

    if summary.get("error"):
        return await state.repo.record_data_feed_event(
            provider_id=provider_id,
            event_type="manual_refresh",
            status="error",
            detail=summary["error"],
            latency_ms=latency_ms,
        )

    await state.repo.mark_data_feed_polled(provider_id)
    return await state.repo.record_data_feed_event(
        provider_id=provider_id,
        event_type="manual_refresh",
        status="success",
        detail=f"Fetched {summary['records']} observation(s); applied to {summary['applied']}.",
        records_received=summary["records"],
        latency_ms=latency_ms,
    )


@router.get("/{provider_id}/events")
async def list_events(provider_id: str, state: AppStateDep, _admin: User = _RequireDataFeeds) -> list[dict]:
    if await state.repo.get_data_feed_config(provider_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown data feed provider")
    return await state.repo.list_data_feed_events(provider_id)
