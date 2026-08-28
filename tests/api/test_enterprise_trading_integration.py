"""#2: the Enterprise-specific Chief Trading Agent, wired into the actual
trade-generation/committee reasoning loop (docs/alpha-intelligence.md section
11.7, Milestone 10 follow-up).

`AppState.submit_trade_idea()`'s enterprise corroboration step
(`_corroborate_trade_with_enterprise_data`) cross-checks an organization-scoped
trade against that organization's own proprietary `EnterprisePosition` holdings,
and `AppState.generate_enterprise_trade_idea()` is the real trade-generation path
for an enterprise customer -- unlike `ChatAgent._enterprise_data_query`, which
only ever *lists* registered datasets."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from schemas import Direction, EnterpriseDataClassification, EnterpriseDataDomain, EnterpriseDataset, InstrumentType, TradeIdea


@pytest.fixture
def client():
    from api_app import state as state_module

    state_module.reset_app_state()
    from api_app.main import app

    with TestClient(app) as c:
        yield c
    state_module.reset_app_state()


def _admin_headers(client) -> dict:
    login = client.post(
        "/api/v1/auth/login", json={"email": "admin@alphagasiq.local", "password": "admin-dev-password"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _activate_via_magic_link(client, email: str, role: str, company_name: str) -> dict:
    from api_app import state as state_module

    admin_headers = _admin_headers(client)
    created = client.post(
        "/api/v1/admin/users",
        json={
            "first_name": "Real",
            "last_name": "User",
            "business_email": email,
            "company_name": company_name,
            "role": role,
        },
        headers=admin_headers,
    ).json()

    sent = state_module._state.email_provider.sent
    token = re.search(r"token=([A-Za-z0-9_-]+)", sent[-1].text_body).group(1)
    verify = client.get(f"/api/v1/auth/magic-link/verify?token={token}", follow_redirects=False)
    session_token = verify.headers["location"].split("access_token=", 1)[1]
    return {"headers": {"Authorization": f"Bearer {session_token}"}, "user": created}


def _make_trade(instrument: str, *, organization_id: str | None, direction: Direction = Direction.LONG) -> TradeIdea:
    return TradeIdea(
        strategy="TEST_ENTERPRISE_CORROBORATION",
        organization_id=organization_id,
        instrument=instrument,
        instrument_type=InstrumentType.FUTURE,
        direction=direction,
        entry=3.0,
        target=3.5,
        stop_or_invalidation=2.8,
        time_horizon="1W",
        expected_return=0.5,
        expected_loss=0.2,
        probability_success=0.6,
        confidence=0.7,
        thesis="test thesis",
    )


def _register_position(state, *, organization_id: str, market: str, direction: str) -> None:
    ds = EnterpriseDataset(
        source_id="00000000-0000-0000-0000-000000000000",
        organization_id=organization_id,
        name="positions",
        domain=EnterpriseDataDomain.POSITION,
        classification=EnterpriseDataClassification.CUSTOMER_POSITION_DATA,
    )
    asyncio.run(state.repo.save_enterprise_dataset(ds))
    asyncio.run(state.repo.save_enterprise_records(str(ds.id), [{"market": market, "direction": direction}]))


def _enterprise_citations(trade) -> list[str]:
    return [c for c in trade.source_citations if c.startswith("enterprise_position:")]


async def test_submit_trade_idea_with_no_organization_id_is_untouched(client):
    """Boot seeds real AlphaConsensus data, so `stored.supporting_data`/`risks` may
    legitimately carry AlphaConsensus/AlphaSignal entries (M7) -- what must stay
    empty here is specifically the enterprise corroboration engine's own output,
    since `trade.organization_id is None` short-circuits it entirely."""
    from api_app import state as state_module

    state = state_module._state
    trade = _make_trade(state.primary_instrument(), organization_id=None)

    await state.submit_trade_idea(trade)

    stored = state.trade_ideas[trade.trade_id]
    assert _enterprise_citations(stored) == []


def test_submit_trade_idea_attaches_aligned_position_as_supporting_data(client):
    trader = _activate_via_magic_link(client, "trader-h@company-h.com", "TRADER", "Company H")
    org_id = trader["user"]["organization_id"]

    from api_app import state as state_module

    state = state_module._state
    instrument = state.primary_instrument()
    _register_position(state, organization_id=org_id, market=instrument, direction="LONG")
    trade = _make_trade(instrument, organization_id=org_id, direction=Direction.LONG)

    asyncio.run(state.submit_trade_idea(trade))

    stored = state.trade_ideas[trade.trade_id]
    assert any("already holds a long position" in s for s in stored.supporting_data)
    assert any(c.startswith("enterprise_position:") for c in stored.source_citations)


def test_submit_trade_idea_attaches_opposing_position_as_a_risk(client):
    trader = _activate_via_magic_link(client, "trader-i@company-i.com", "TRADER", "Company I")
    org_id = trader["user"]["organization_id"]

    from api_app import state as state_module

    state = state_module._state
    instrument = state.primary_instrument()
    _register_position(state, organization_id=org_id, market=instrument, direction="SHORT")
    trade = _make_trade(instrument, organization_id=org_id, direction=Direction.LONG)

    asyncio.run(state.submit_trade_idea(trade))

    stored = state.trade_ideas[trade.trade_id]
    assert any("opposing short position" in r for r in stored.risks)
    assert not any("already holds a" in s for s in stored.supporting_data)


def test_submit_trade_idea_never_sees_another_organizations_positions(client):
    org_a = _activate_via_magic_link(client, "trader-j@company-j.com", "TRADER", "Company J")
    org_b = _activate_via_magic_link(client, "trader-k@company-k.com", "TRADER", "Company K")

    from api_app import state as state_module

    state = state_module._state
    instrument = state.primary_instrument()
    _register_position(state, organization_id=org_b["user"]["organization_id"], market=instrument, direction="SHORT")
    trade = _make_trade(instrument, organization_id=org_a["user"]["organization_id"], direction=Direction.LONG)

    asyncio.run(state.submit_trade_idea(trade))

    stored = state.trade_ideas[trade.trade_id]
    assert _enterprise_citations(stored) == []
    assert not any("opposing" in r or "already holds a" in r for r in stored.risks + stored.supporting_data)


def test_generate_enterprise_trade_idea_submits_through_the_normal_pipeline(client):
    trader = _activate_via_magic_link(client, "trader-l@company-l.com", "TRADER", "Company L")
    org_id = trader["user"]["organization_id"]

    from api_app import state as state_module

    state = state_module._state
    approval = asyncio.run(state.generate_enterprise_trade_idea(organization_id=org_id))

    # DirectionalStrategyAgent may data-driven-SKIP -- both outcomes are legitimate.
    if approval is None:
        return
    stored = state.trade_ideas[approval.trade_id]
    assert stored.organization_id == org_id
    assert approval.trade_id in state.committee_decisions


def test_generate_enterprise_trade_idea_returns_none_when_strategy_agent_skips(client, monkeypatch):
    trader = _activate_via_magic_link(client, "trader-m@company-m.com", "TRADER", "Company M")
    org_id = trader["user"]["organization_id"]

    from api_app import state as state_module
    from schemas import AgentResult, AgentStatus, AgentType

    state = state_module._state

    async def _no_trade_ideas():
        from agents_service import ResearchCycleResult

        placeholder = AgentResult(
            agent_id="test",
            agent_name="test",
            agent_type=AgentType.DIRECTIONAL_STRATEGY,
            version="0.0.0",
            status=AgentStatus.SKIPPED,
            last_execution_time=datetime.utcnow(),
            execution_duration_ms=0.0,
        )
        return ResearchCycleResult(
            supply=placeholder,
            demand=placeholder,
            storage=placeholder,
            weather=placeholder,
            strategy=placeholder,
            trade_ideas=[],
            chief=None,
        )

    monkeypatch.setattr(state, "_run_chief_trading_research", _no_trade_ideas)

    approval = asyncio.run(state.generate_enterprise_trade_idea(organization_id=org_id))

    assert approval is None
