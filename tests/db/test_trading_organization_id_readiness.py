"""Tenant-isolation retrofit (docs/alpha-intelligence.md section 11.1, Milestone
9): `organization_id` schema readiness on the core trading tables
(`trade_ideas`/`committee_decisions`/`risk_checks`/`approvals`). Proves the value
set on a submitted `TradeIdea.organization_id` actually round-trips onto all four
rows through the real `AppState.submit_trade_idea()` pipeline -- not just the
trade_ideas row -- and that the untouched (`None`) default still works exactly as
before (the "schema readiness only, default None = unchanged behavior" claim)."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from db.models import ApprovalRow, CommitteeDecisionRow, RiskCheckRow, TradeIdeaRow
from schemas import Direction, InstrumentType, TradeIdea


@pytest.fixture
def client():
    from api_app import state as state_module

    state_module.reset_app_state()
    from api_app.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c
    state_module.reset_app_state()


def _make_trade(*, organization_id: str | None, instrument: str) -> TradeIdea:
    return TradeIdea(
        organization_id=organization_id,
        strategy="TEST_ORG_READINESS",
        instrument=instrument,
        instrument_type=InstrumentType.FUTURE,
        direction=Direction.LONG,
        entry=3.0,
        target=3.1,
        stop_or_invalidation=2.9,
        time_horizon="1W",
        expected_return=0.1,
        expected_loss=-0.05,
        probability_success=0.7,
        confidence=0.7,
        thesis="Org readiness round-trip test.",
    )


async def _fetch_organization_ids(repo, trade_id: str) -> dict:
    async with repo.session_factory() as session:
        trade_row = (
            await session.execute(select(TradeIdeaRow).where(TradeIdeaRow.trade_id == str(trade_id)))
        ).scalar_one()
        decision_row = (
            await session.execute(
                select(CommitteeDecisionRow).where(CommitteeDecisionRow.original_trade_id == str(trade_id))
            )
        ).scalar_one()
        risk_row = (
            await session.execute(select(RiskCheckRow).where(RiskCheckRow.trade_id == str(trade_id)))
        ).scalar_one()
        approval_row = (
            await session.execute(select(ApprovalRow).where(ApprovalRow.trade_id == str(trade_id)))
        ).scalar_one()
    return {
        "trade_ideas": trade_row.organization_id,
        "committee_decisions": decision_row.organization_id,
        "risk_checks": risk_row.organization_id,
        "approvals": approval_row.organization_id,
    }


def test_organization_id_round_trips_onto_all_four_trading_tables(client):
    from api_app import state as state_module

    state = state_module._state
    instrument = state.primary_instrument()
    trade = _make_trade(organization_id="org-a", instrument=instrument)
    asyncio.run(state.submit_trade_idea(trade))

    organization_ids = asyncio.run(_fetch_organization_ids(state.repo, trade.trade_id))
    assert organization_ids == {
        "trade_ideas": "org-a",
        "committee_decisions": "org-a",
        "risk_checks": "org-a",
        "approvals": "org-a",
    }


def test_unset_organization_id_stays_none_on_all_four_tables(client):
    """The "schema readiness only, default None = unchanged behavior" claim:
    the system-generated research-cycle path (`worker.py`) never sets
    `organization_id`, so it must land as `NULL` everywhere, exactly as before
    this column existed."""
    from api_app import state as state_module

    state = state_module._state
    instrument = state.primary_instrument()
    trade = _make_trade(organization_id=None, instrument=instrument)
    asyncio.run(state.submit_trade_idea(trade))

    organization_ids = asyncio.run(_fetch_organization_ids(state.repo, trade.trade_id))
    assert organization_ids == {
        "trade_ideas": None,
        "committee_decisions": None,
        "risk_checks": None,
        "approvals": None,
    }
