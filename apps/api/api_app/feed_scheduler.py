"""Per-feed polling scheduler — makes the admin Data Feeds page's controls real.

`DataFeedConfigRow` has carried `enabled`, `paused` and `polling_frequency_seconds`
since Milestone 8, and the admin page has always let an operator edit them, but
nothing read them: ingestion was hardcoded (EIA/NOAA on the research cycle, the two
market feeds on the fast cycle) and every other registered feed was never polled at
all. Changing a frequency in the UI did nothing.

This module closes that. Each worker tick asks which feeds are **due** — enabled,
not paused, and `polling_frequency_seconds` elapsed since `last_polled_at` — and
ingests exactly those through `AppState.ingest_from_provider`, which routes the
result into the right engine input rather than discarding it.

Two deliberate choices:

- **A NULL frequency means "use this feed's default"**, not "never poll". The
  defaults below are set from each upstream's real publication cadence, so an
  operator who never touches the page still gets sensible behaviour.
- **A frequency below a provider's own floor is honoured but pointless**, and the
  scheduler says so in the returned summary rather than silently clamping. Polling
  EIA every 10s cannot make weekly storage data any fresher; the operator should
  see that, not be quietly overruled.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger("alphagasiq.feeds")

# Default poll interval per provider when the admin config leaves it NULL, chosen
# from how often the upstream *actually* publishes.
DEFAULT_POLL_SECONDS: dict[str, int] = {
    # Market quotes: continuous upstream (though ~15 min delayed on the free feeds).
    "cme_live": 10,
    "mock_cme": 10,
    "ice_live": 10,
    "mock_ice": 10,
    # EIA storage is weekly (Thu 10:30 ET); hourly is already generous.
    "eia": 3600,
    # NOAA forecasts refresh roughly hourly; 15 min catches a revision promptly.
    "noaa_nws": 900,
    # NHC advisories are ~6-hourly, more often during an active storm.
    "nhc_tropical": 1800,
    # ISO/RTO demand + generation post every 5 minutes to hourly by ISO.
    "iso_rto_public": 900,
    # EDGAR filings arrive continuously but matter at a daily cadence.
    "sec_edgar": 3600,
    # News: fast enough to be useful, slow enough to be polite to the publisher.
    "rss_news": 300,
    "mock_news": 300,
}

# Feeds whose scheduled poll is deliberately a partial fetch. The Henry Hub curve is
# one request per contract; at a short interval a full refresh would be thousands of
# upstream requests an hour, so the schedule takes the front month and the deferred
# months come with the research cycle.
PARTIAL_ON_SCHEDULE = ("cme_live", "mock_cme")

# How far below an upstream's real publication cadence a configured frequency has to
# be before it is worth telling the operator it buys nothing.
_POINTLESS_BELOW: dict[str, int] = {
    "eia": 900,
    "sec_edgar": 900,
    "nhc_tropical": 300,
    "noaa_nws": 300,
}


def effective_interval(provider_id: str, configured: int | None) -> int | None:
    """The interval this feed should actually be polled at.

    `None` means "do not poll on a schedule" — used for providers with no default
    and no configured value, i.e. the honest `NotImplementedProvider` stubs, which
    have nothing to fetch.
    """
    if configured is not None and configured > 0:
        return configured
    return DEFAULT_POLL_SECONDS.get(provider_id)


def is_due(config: dict[str, Any], now: datetime) -> bool:
    """Whether this feed should be ingested on this tick."""
    if not config.get("enabled", True) or config.get("paused", False):
        return False
    interval = effective_interval(config["provider_id"], config.get("polling_frequency_seconds"))
    if interval is None:
        return False
    last = config.get("last_polled_at")
    if last is None:
        return True  # never polled — pick it up on the first tick, not after one interval
    return now - last >= timedelta(seconds=interval)


def next_due_at(config: dict[str, Any]) -> datetime | None:
    """When this feed is next due, for the admin page. `None` = not scheduled."""
    interval = effective_interval(config["provider_id"], config.get("polling_frequency_seconds"))
    if interval is None or not config.get("enabled", True) or config.get("paused", False):
        return None
    last = config.get("last_polled_at")
    if last is None:
        return None  # due now
    return last + timedelta(seconds=interval)


def advisory_for(provider_id: str, configured: int | None) -> str | None:
    """A note when a configured frequency cannot deliver what it implies. Advisory
    only — the scheduler still honours the operator's setting."""
    if configured is None or configured <= 0:
        return None
    floor = _POINTLESS_BELOW.get(provider_id)
    if floor is not None and configured < floor:
        return (
            f"{provider_id} publishes far less often than every {configured}s; "
            f"polling faster than ~{floor}s re-reads the same data."
        )
    if provider_id in ("cme_live", "ice_live") and configured < 60:
        return (
            "The free Yahoo NYMEX/ICE quotes behind this feed are ~15 minutes delayed "
            "at source, so a sub-minute interval makes the dashboard feel live without "
            "the data being any fresher."
        )
    return None


async def poll_due_feeds(state, *, now: datetime | None = None) -> dict[str, Any]:
    """Ingest every feed that is due. Returns a per-tick summary for the worker log.

    Each feed is independent: one failing upstream must never stop the others, so
    every ingest is guarded and reported on its own.
    """
    now = now or datetime.utcnow()
    result: dict[str, Any] = {"polled": [], "skipped": 0, "errors": []}

    try:
        configs = await state.repo.list_data_feed_configs()
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"config read failed: {type(exc).__name__}")
        return result

    for config in configs:
        provider_id = config["provider_id"]
        if not is_due(config, now):
            result["skipped"] += 1
            continue

        # The forward curve costs one upstream request per contract, so a scheduled
        # poll takes the front month only; the full curve refreshes on the research
        # cadence (`worker.py`). Every other feed is a single request either way.
        full = provider_id not in PARTIAL_ON_SCHEDULE
        summary = await state.ingest_from_provider(provider_id, full=full)

        # Stamp the attempt either way: a feed whose upstream is down must not be
        # retried on every single tick, which would hammer a struggling provider.
        try:
            await state.repo.mark_data_feed_polled(provider_id, now)
        except Exception:  # noqa: BLE001
            logger.debug("Could not stamp last_polled_at for %s", provider_id, exc_info=True)

        if summary.get("error"):
            result["errors"].append(f"{provider_id}: {summary['error']}")
            await _record(state, provider_id, "error", summary["error"])
        else:
            result["polled"].append(
                {"provider_id": provider_id, "records": summary["records"], "applied": summary["applied"]}
            )
            await _record(
                state, provider_id, "success",
                f"Scheduled poll fetched {summary['records']} observation(s); applied to {summary['applied']}.",
                records=summary["records"],
            )

    return result


async def _record(state, provider_id: str, status: str, detail: str, records: int | None = None) -> None:
    """Write the ingestion-log entry the admin page's Events tab reads. Best-effort."""
    try:
        await state.repo.record_data_feed_event(
            provider_id=provider_id, event_type="scheduled_poll", status=status,
            detail=detail[:1000], records_received=records,
        )
    except Exception:  # noqa: BLE001
        logger.debug("Could not record feed event for %s", provider_id, exc_info=True)
