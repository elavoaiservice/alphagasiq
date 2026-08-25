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

from .state import PRIMARY_INSTRUMENT, get_app_state

logging.basicConfig(level=logging.INFO)
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
                instrument=PRIMARY_INSTRUMENT,
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
            )
            for trade in result.trade_ideas:
                await state.submit_trade_idea(trade)
            logger.info("Research cycle complete: %d trade idea(s)", len(result.trade_ideas))
        except Exception:
            logger.exception("Worker research cycle failed")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    asyncio.run(run_forever())
