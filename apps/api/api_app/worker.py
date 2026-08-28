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

from .logging_config import configure_logging
from .state import get_app_state

configure_logging(log_level=get_settings().log_level)
logger = logging.getLogger("alphagasiq.worker")


async def run_forever() -> None:
    interval = int(os.environ.get("WORKER_INTERVAL_SECONDS", "300"))
    state = await get_app_state()
    logger.info("AlphaGasIQ worker started; research cycle every %ss", interval)
    while True:
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
                weather_kwargs=dict(
                    model="GFS", run="latest", comparison_run="previous",
                    hdd_run=2.8, hdd_comparison=2.2, cdd_run=4.0, cdd_comparison=4.5,
                ),
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

        await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(run_forever())
