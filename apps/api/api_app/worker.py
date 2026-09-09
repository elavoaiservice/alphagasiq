"""Minimal background worker: periodically re-runs the Chief Trading Agent research
cycle so trade ideas refresh without a human hitting `POST /agents/chief-trading/run`.

This stands in for the full Temporal-orchestrated ingestion/research workflows
described in docs/architecture.md; the `WorkflowEngine` interface those workflows will
implement against is intentionally not built yet (see the milestone plan) — this
script is the honest, minimal Milestone 1-2 equivalent so `docker compose up` has a
running worker container.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date

from config import get_settings

from . import feed_scheduler
from .logging_config import configure_logging
from .state import get_app_state

configure_logging(log_level=get_settings().log_level)
logger = logging.getLogger("alphagasiq.worker")


async def run_forever() -> None:
    """Two cadences, deliberately decoupled.

    Market prices move continuously and are cheap to fetch; the research cycle runs
    the whole multi-agent organization (LLM calls, quant models) and is expensive in
    both time and Anthropic spend. Running them on one timer forced a bad trade-off:
    fast prices meant burning tokens every minute. So `MARKET_REFRESH_SECONDS`
    (default 10) drives the loop, and the full research cycle runs only once
    `WORKER_INTERVAL_SECONDS` (default 300) has elapsed.

    The fast pass fetches only the front month plus TTF/FX (3 upstream requests); the
    full forward curve is refreshed on the research cadence, because one request per
    contract at a 10s cadence would be ~4,700 Yahoo requests an hour and invite
    throttling.

    MARKET_REFRESH_SECONDS can go as low as 5. Be aware of the ceiling on usefulness:
    the free Yahoo NYMEX/ICE quotes behind both legs are ~15 minutes delayed at source,
    so polling faster than that re-reads the same number -- it makes the dashboard feel
    live without making the data any fresher. Nothing here can outpace the publisher.
    """
    research_interval = int(os.environ.get("WORKER_INTERVAL_SECONDS", "300"))
    market_interval = max(5, int(os.environ.get("MARKET_REFRESH_SECONDS", "10")))
    state = await get_app_state()
    logger.info(
        "AlphaGasIQ worker started; market refresh every %ss, research cycle every %ss",
        market_interval, research_interval,
    )
    # Run the full cycle on the first pass rather than waiting one whole interval.
    since_research = research_interval
    while True:
        try:
            # Per-feed scheduling: each registered feed is ingested at its own
            # configured `polling_frequency_seconds` (admin Data Feeds page), not on
            # one hardcoded cadence. Feeds that are disabled, paused, or not yet due
            # are skipped. `MARKET_REFRESH_SECONDS` is the tick rate — the resolution
            # at which a feed can become due — not the rate any one feed is polled.
            poll_summary = await feed_scheduler.poll_due_feeds(state)
            if poll_summary["polled"] or poll_summary["errors"]:
                logger.info("Feed poll: %s", poll_summary)
        except Exception:
            logger.exception("Worker feed poll failed")

        if since_research < research_interval:
            since_research += market_interval
            await asyncio.sleep(market_interval)
            continue
        since_research = 0

        try:
            # The full forward curve on the slower cadence: the scheduler's fast pass
            # only refreshes the front month, because the deferred months cost one
            # upstream request each. EIA/NOAA are kept current by the scheduler on
            # their own intervals, so the research cycle no longer re-fetches them.
            logger.info("Full forward curve: %s", await state.refresh_market_data(full=True))
        except Exception:
            logger.exception("Worker full market refresh failed")

        try:
            current_price = state.market_curve[0].value if state.market_curve else 3.0
            week_balance = sum(b.balance_bcf for b in state.balances[-7:])
            result = await state.chief_trading_agent.run_research_cycle(
                instrument=state.primary_instrument(),
                current_price=current_price,
                balances=state.balances,
                five_year_average_bcf=state.storage_baseline["five_year_average_bcf"],
                last_year_bcf=state.storage_baseline["year_ago_inventory_bcf"],
                as_of=date.today(),
                weather_kwargs=state.weather_kwargs,
                market_consensus_bcf=round(week_balance) + 3,
                disabled_agent_types=await state._disabled_agent_types(),
            )
            for trade in result.trade_ideas:
                await state.submit_trade_idea(trade)
            logger.info("Research cycle complete: %d trade idea(s)", len(result.trade_ideas))
        except Exception:
            logger.exception("Worker research cycle failed")

        try:
            # Milestone 10 follow-up (docs/alpha-intelligence.md section 11.7): opportunity
            # generation previously had no scheduled cadence at all -- admin/user-triggered
            # only. Same interval as the research cycle above is a provisional, documented
            # choice (not derived from real customer usage patterns yet); decoupling it onto
            # its own interval is a small follow-up if that ever proves too frequent/coarse.
            opportunities_by_org = await state.generate_enterprise_opportunities_for_all_organizations()
            total_generated = sum(len(v) for v in opportunities_by_org.values())
            if opportunities_by_org:
                logger.info(
                    "Enterprise opportunity generation complete: %d organization(s), %d opportunity(ies)",
                    len(opportunities_by_org),
                    total_generated,
                )
        except Exception:
            logger.exception("Worker enterprise opportunity generation failed")

        try:
            # Gap-closure follow-up (docs/alpha-intelligence.md section 11.6): retention
            # purging previously had no scheduled cadence at all -- admin/API-triggered
            # only. Same interval as the two blocks above is a provisional, documented
            # choice (not derived from real customer retention needs yet); decoupling it
            # onto its own, likely coarser, interval is a small follow-up if this ever
            # proves too frequent for how slowly retention windows actually expire.
            purge_results = await state.apply_retention_policies_for_all_organizations()
            total_purged = sum(r["records_purged"] for r in purge_results)
            if purge_results:
                logger.info(
                    "Retention purge cycle complete: %d (organization, classification) pair(s) checked, %d record(s) purged",
                    len(purge_results),
                    total_purged,
                )
        except Exception:
            logger.exception("Worker retention purge cycle failed")

        since_research += market_interval
        await asyncio.sleep(market_interval)


if __name__ == "__main__":
    asyncio.run(run_forever())
