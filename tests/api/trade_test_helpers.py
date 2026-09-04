"""Shared helper for tests that need a trade idea to exist and reach the AI
Investment Committee / Risk Governor / human-approval pipeline deterministically.

Boot's `_run_initial_research_cycle()` (see `AppState._seed_market_and_fundamentals`)
feeds real calendar dates into the synthetic storage/weather signal generators, so on
some dates `DirectionalStrategyAgent` legitimately returns SKIPPED ("storage and
weather signals do not agree on direction") and no trade idea is produced at boot.
Tests that need a trade idea used to just assume `trades[0]` existed -- flaky against
the calendar. This helper instead submits its own `TradeIdea` directly through the
real `AppState.submit_trade_idea()` pipeline (real committee deliberation, real Risk
Governor evaluation, real approval-state routing) -- it only bypasses the
date-sensitive `DirectionalStrategyAgent` signal-generation step itself, which is the
one part of the pipeline whose outcome is calendar-dependent.
"""

from __future__ import annotations

import asyncio

from schemas import Direction, InstrumentType, TradeIdea


def create_deterministic_trade_idea(client) -> dict:
    """Submits a fresh, deterministic long trade idea and returns its flat dict as
    `GET /trade-ideas` would list it (`trade_id`, `entry`, `instrument`, ...)."""
    from api_app import state as state_module

    state = state_module._state
    instrument = state.primary_instrument()
    entry = state.mark_price(instrument)

    trade = TradeIdea(
        strategy="TEST_DETERMINISTIC",
        instrument=instrument,
        instrument_type=InstrumentType.FUTURE,
        direction=Direction.LONG,
        entry=entry,
        target=entry * 1.03,
        stop_or_invalidation=entry * 0.98,
        time_horizon="1W",
        expected_return=entry * 0.03,
        expected_loss=entry * 0.02,
        probability_success=0.75,
        confidence=0.8,
        thesis="Deterministically constructed trade idea for test coverage; not date-dependent.",
    )
    asyncio.run(state.submit_trade_idea(trade))

    trades = client.get("/api/v1/trade-ideas").json()
    return next(t for t in trades if t["trade_id"] == str(trade.trade_id))


def get_approval_for_trade(client, trade_id: str) -> dict:
    approvals = client.get("/api/v1/approvals").json()
    return next(a for a in approvals if a["trade_id"] == str(trade_id))
