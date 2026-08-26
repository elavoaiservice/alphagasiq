"""Persistence layer tests (Milestone: SQLAlchemy-backed repository).

Exercises `SqlAppRepository` directly (independent of `AppState`) to prove data
round-trips correctly, and separately proves the exact scenario the whole feature
exists for: a second repository instance opened against the same on-disk sqlite file
sees everything the first one wrote, i.e. state survives a process restart.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from db import SqlAppRepository
from schemas import (
    Direction,
    ForecastHorizon,
    InstrumentType,
    InvestmentCommitteeDecision,
    ModelType,
    OutcomeQuadrant,
    PostTradeAnalysis,
    PriceForecast,
    RecommendedAction,
    RiskCheckResult,
    RiskLimits,
    RiskRuleOutcome,
    RiskVerdict,
    TradeIdea,
)


def make_trade() -> TradeIdea:
    return TradeIdea(
        strategy="test-strategy",
        instrument="NGZ26",
        instrument_type=InstrumentType.FUTURE,
        direction=Direction.LONG,
        entry=3.0,
        target=3.5,
        stop_or_invalidation=2.8,
        time_horizon="7d",
        expected_return=0.15,
        expected_loss=-0.05,
        probability_success=0.6,
        confidence=0.7,
        thesis="test thesis",
    )


def make_forecast(instrument: str) -> PriceForecast:
    return PriceForecast(
        instrument=instrument,
        horizon=ForecastHorizon.SEVEN_DAY,
        price_forecast=3.4,
        return_forecast=0.13,
        up_probability=0.65,
        down_probability=0.35,
        expected_volatility=0.2,
        confidence=0.7,
        model_contributions={"LINEAR_REGRESSION": 1.0},
    )


def make_decision(trade: TradeIdea) -> InvestmentCommitteeDecision:
    return InvestmentCommitteeDecision(
        original_trade=trade,
        bull_case="bull",
        bear_case="bear",
        skeptic_case="skeptic",
        data_quality_assessment="ok",
        portfolio_effect="fine",
        consensus_score=0.7,
        recommended_action=RecommendedAction.APPROVE_FOR_REVIEW,
    )


def make_risk_check(trade_id: uuid.UUID) -> RiskCheckResult:
    return RiskCheckResult(
        trade_id=trade_id,
        verdict=RiskVerdict.ALLOW,
        rule_results=[RiskRuleOutcome(rule="max_position_size", verdict=RiskVerdict.ALLOW, passed=True, detail="ok")],
        governor_version="1.0.0",
    )


def make_post_trade_analysis(trade_id: uuid.UUID) -> PostTradeAnalysis:
    return PostTradeAnalysis(
        trade_id=trade_id,
        expected_outcome={"expected_return": 0.15},
        actual_outcome={"actual_return_per_unit": 0.1},
        forecast_error=0.03,
        thesis_accuracy=0.8,
        timing_accuracy=0.6,
        risk_accuracy=0.9,
        quadrant=OutcomeQuadrant.GOOD_DECISION_GOOD_OUTCOME,
        quant_model_type=ModelType.LINEAR_REGRESSION,
        quant_model_version="1.0.0",
        quant_predicted_return=0.13,
        quant_forecast_error=0.03,
        quant_up_probability=0.65,
    )


@pytest.fixture
async def repo():
    r = SqlAppRepository("sqlite+aiosqlite:///:memory:")
    await r.init_schema()
    yield r
    await r.dispose()


async def test_save_and_hydrate_trade_idea(repo):
    trade = make_trade()
    forecast = make_forecast(trade.instrument)
    await repo.save_trade_idea(trade, forecast)

    data = await repo.hydrate()
    reloaded = data["trade_ideas"][str(trade.trade_id)]
    assert reloaded.instrument == trade.instrument
    assert reloaded.entry == trade.entry
    assert reloaded.catalysts == trade.catalysts

    reloaded_forecast = data["forecasts"][str(trade.trade_id)]
    assert reloaded_forecast.instrument == forecast.instrument
    assert reloaded_forecast.price_forecast == forecast.price_forecast


async def test_full_trade_lifecycle_round_trips(repo):
    trade = make_trade()
    await repo.save_trade_idea(trade, None)

    decision = make_decision(trade)
    await repo.save_committee_decision(trade.trade_id, decision)

    risk_check = make_risk_check(trade.trade_id)
    await repo.save_risk_check(trade.trade_id, risk_check)

    approval_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    await repo.save_approval(
        approval_id=approval_id,
        trade_id=trade.trade_id,
        state="HUMAN_REVIEW",
        actions=[{"action": "APPROVE", "payload": {}, "user_id": "u1", "at": now.isoformat()}],
        updated_at=now,
    )

    await repo.append_decision_journal_entry(trade.trade_id, {"recorded_at": now.isoformat(), "thesis": trade.thesis})

    analysis = make_post_trade_analysis(trade.trade_id)
    await repo.save_post_trade_analysis(analysis)

    data = await repo.hydrate()

    assert data["committee_decisions"][str(trade.trade_id)].bull_case == "bull"
    assert data["risk_checks"][str(trade.trade_id)].verdict == RiskVerdict.ALLOW

    approvals_by_id = {a["id"]: a for a in data["approvals"]}
    assert approvals_by_id[str(approval_id)]["state"] == "HUMAN_REVIEW"
    assert approvals_by_id[str(approval_id)]["actions"][0]["user_id"] == "u1"

    assert len(data["decision_journal"][str(trade.trade_id)]) == 1

    reloaded_analysis = data["post_trade_analyses"][str(trade.trade_id)]
    assert reloaded_analysis.quant_model_type == ModelType.LINEAR_REGRESSION
    assert reloaded_analysis.quadrant == OutcomeQuadrant.GOOD_DECISION_GOOD_OUTCOME


async def test_approval_upsert_by_id_reflects_latest_state(repo):
    trade = make_trade()
    await repo.save_trade_idea(trade, None)
    approval_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    await repo.save_approval(
        approval_id=approval_id, trade_id=trade.trade_id, state="HUMAN_REVIEW", actions=[], updated_at=now
    )
    await repo.save_approval(
        approval_id=approval_id,
        trade_id=trade.trade_id,
        state="EXECUTED_SIMULATION",
        actions=[{"action": "APPROVE", "payload": {}, "user_id": "u1", "at": now.isoformat()}],
        updated_at=now,
    )

    data = await repo.hydrate()
    matching = [a for a in data["approvals"] if a["id"] == str(approval_id)]
    assert len(matching) == 1, "expected exactly one row after upsert, not a duplicate"
    assert matching[0]["state"] == "EXECUTED_SIMULATION"


async def test_risk_limits_hydrate_returns_most_recent(repo):
    older = RiskLimits(
        max_position_size=100,
        max_risk_per_trade=0.01,
        max_daily_loss=1000,
        max_drawdown=0.1,
        max_portfolio_var=0.05,
        max_sector_exposure=0.3,
        max_contract_exposure=0.2,
        max_correlated_exposure=0.4,
        effective_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    newer = RiskLimits(
        max_position_size=200,
        max_risk_per_trade=0.02,
        max_daily_loss=2000,
        max_drawdown=0.2,
        max_portfolio_var=0.1,
        max_sector_exposure=0.4,
        max_contract_exposure=0.3,
        max_correlated_exposure=0.5,
        effective_from=datetime(2024, 1, 1, tzinfo=timezone.utc),
        set_by_user_id="risk-manager-1",
    )
    await repo.save_risk_limits(older)
    await repo.save_risk_limits(newer)

    data = await repo.hydrate()
    assert data["risk_limits"].max_position_size == 200
    assert data["risk_limits"].set_by_user_id == "risk-manager-1"


async def test_contact_inquiry_save_and_list_round_trips_and_never_touches_users(repo):
    """Regression test for the account-provisioning invariant: `ContactInquiryRow` is
    a standalone table with no relationship to `User`/`Organization`/`MagicLinkToken`
    — this only checks the round-trip and ordering, since the "never creates a user"
    guarantee is structural (no such table/FK exists yet), not something a repository
    test can violate."""
    first_id = await repo.save_contact_inquiry(
        first_name="Jane",
        last_name="Doe",
        business_email="jane.doe@example.com",
        company_name="Example Energy Corp",
        job_title="VP Trading",
        phone="555-0100",
        inquiry_type="SALES",
        message="Interested in a platform demo.",
    )
    second_id = await repo.save_contact_inquiry(
        first_name="John",
        last_name="Smith",
        business_email="john.smith@example.com",
        company_name="Smith Gas LLC",
        job_title=None,
        phone=None,
        inquiry_type="GENERAL",
        message="General question about coverage.",
    )

    inquiries = await repo.list_contact_inquiries()
    assert [i["id"] for i in inquiries] == [second_id, first_id], "most recent first"

    saved = next(i for i in inquiries if i["id"] == first_id)
    assert saved["business_email"] == "jane.doe@example.com"
    assert saved["company_name"] == "Example Energy Corp"
    assert saved["job_title"] == "VP Trading"
    assert saved["inquiry_type"] == "SALES"

    saved_optional = next(i for i in inquiries if i["id"] == second_id)
    assert saved_optional["job_title"] is None
    assert saved_optional["phone"] is None


async def test_hydrate_on_empty_db_is_well_shaped(repo):
    data = await repo.hydrate()
    assert data["trade_ideas"] == {}
    assert data["forecasts"] == {}
    assert data["committee_decisions"] == {}
    assert data["risk_checks"] == {}
    assert data["approvals"] == []
    assert data["decision_journal"] == {}
    assert data["post_trade_analyses"] == {}
    assert data["risk_limits"] is None


async def test_mixed_naive_and_aware_datetimes_round_trip(repo):
    """Regression test: `TradeIdea.created_at` defaults to naive `datetime.utcnow()`
    while `expires_at` is commonly set timezone-aware (e.g.
    `datetime.now(timezone.utc) + timedelta(...)`). sqlite tolerates this mix
    silently, but real Postgres via `asyncpg` raised `TypeError: can't subtract
    offset-naive and offset-aware datetimes` on exactly this combination — caught by
    validating this repository against a live local Postgres instance. `_naive_utc()`
    normalizes both to naive UTC before binding; this test pins that behavior even
    though sqlite alone can't detect a regression here.
    """
    trade = make_trade()
    trade.expires_at = datetime.now(timezone.utc)
    assert trade.created_at.tzinfo is None
    assert trade.expires_at.tzinfo is not None

    await repo.save_trade_idea(trade, None)
    data = await repo.hydrate()
    reloaded = data["trade_ideas"][str(trade.trade_id)]
    assert reloaded.expires_at is not None


async def test_data_survives_across_repository_instances_same_file_db(tmp_path):
    """The actual guarantee this feature exists for: state durability across a process
    restart. A file-based sqlite DB (not `:memory:`) stands in for that restart here —
    opening a brand-new `SqlAppRepository` against the same file is equivalent to a
    fresh process picking the DB back up."""
    db_path = tmp_path / "persistence_test.db"
    database_url = f"sqlite+aiosqlite:///{db_path}"

    first = SqlAppRepository(database_url)
    await first.init_schema()
    trade = make_trade()
    await first.save_trade_idea(trade, make_forecast(trade.instrument))
    await first.save_committee_decision(trade.trade_id, make_decision(trade))
    await first.dispose()

    second = SqlAppRepository(database_url)
    data = await second.hydrate()
    assert str(trade.trade_id) in data["trade_ideas"]
    assert data["trade_ideas"][str(trade.trade_id)].thesis == trade.thesis
    assert str(trade.trade_id) in data["committee_decisions"]
    await second.dispose()


async def test_seed_rbac_defaults_creates_eight_roles_and_permission_grants(repo):
    await repo.seed_rbac_defaults()

    roles = await repo.list_roles()
    assert {r["name"] for r in roles} == {
        "SUPER_ADMIN",
        "ADMIN",
        "TRADER",
        "RISK_MANAGER",
        "RESEARCHER",
        "EXECUTIVE",
        "VIEWER",
        "API_USER",
    }

    trader = await repo.get_role_by_name("TRADER")
    assert trader is not None
    admin = await repo.get_role_by_name("ADMIN")
    assert admin is not None
    assert await repo.get_role_by_id(admin["id"]) == admin


async def test_seed_rbac_defaults_is_idempotent(repo):
    """Regression test: re-running the seed (as happens on every process boot) must
    not create duplicate Role/Permission rows or duplicate RolePermission grants."""
    await repo.seed_rbac_defaults()
    first_roles = await repo.list_roles()
    await repo.seed_rbac_defaults()
    await repo.seed_rbac_defaults()
    second_roles = await repo.list_roles()
    assert len(first_roles) == len(second_roles) == 8


async def test_organization_create_lookup_and_list(repo):
    org = await repo.create_organization(name="Acme Gas Trading", country="United States")
    assert org["status"] == "ACTIVE"
    assert org["data_entitlements"] == {}

    found = await repo.find_organization_by_name("Acme Gas Trading")
    assert found is not None
    assert found["id"] == org["id"]

    assert await repo.find_organization_by_name("Does Not Exist Co") is None
    assert await repo.get_organization(org["id"]) == found

    listed = await repo.list_organizations()
    assert [o["id"] for o in listed] == [org["id"]]


async def test_user_create_and_lookup_round_trips(repo):
    await repo.seed_rbac_defaults()
    role = await repo.get_role_by_name("RESEARCHER")
    org = await repo.create_organization(name="Northwind Energy")

    created = await repo.create_user(
        first_name="Ada",
        last_name="Lovelace",
        email="Ada.Lovelace@Northwind.example",
        organization_id=org["id"],
        role_id=role["id"],
        status="INVITED",
        job_title="Research Analyst",
        created_by="u-admin-1",
    )
    assert created["status"] == "INVITED"

    by_id = await repo.get_user_by_id(created["id"])
    assert by_id == created

    # Email lookups are case-insensitive; storage itself preserves what was written.
    by_email = await repo.get_user_by_email("ada.lovelace@northwind.example")
    assert by_email is not None
    assert by_email["id"] == created["id"]

    listed = await repo.list_users()
    assert [u["id"] for u in listed] == [created["id"]]


async def test_update_user_status_persists_and_missing_user_returns_none(repo):
    await repo.seed_rbac_defaults()
    role = await repo.get_role_by_name("VIEWER")
    org = await repo.create_organization(name="Southbay Utilities")
    user = await repo.create_user(
        first_name="Sam",
        last_name="Rivera",
        email="sam.rivera@southbay.example",
        organization_id=org["id"],
        role_id=role["id"],
        status="INVITED",
    )

    updated = await repo.update_user_status(user["id"], "REVOKED")
    assert updated["status"] == "REVOKED"
    assert (await repo.get_user_by_id(user["id"]))["status"] == "REVOKED"

    assert await repo.update_user_status("no-such-user-id", "REVOKED") is None
