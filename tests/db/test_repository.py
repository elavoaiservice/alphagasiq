"""Persistence layer tests (Milestone: SQLAlchemy-backed repository).

Exercises `SqlAppRepository` directly (independent of `AppState`) to prove data
round-trips correctly, and separately proves the exact scenario the whole feature
exists for: a second repository instance opened against the same on-disk sqlite file
sees everything the first one wrote, i.e. state survives a process restart.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

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


async def test_mark_user_activated_promotes_status_and_stamps_timestamps(repo):
    await repo.seed_rbac_defaults()
    role = await repo.get_role_by_name("TRADER")
    org = await repo.create_organization(name="Activation Test Co")
    user = await repo.create_user(
        first_name="Casey",
        last_name="Kim",
        email="casey.kim@activationtest.example",
        organization_id=org["id"],
        role_id=role["id"],
        status="INVITED",
    )
    assert user["activated_at"] is None

    activated = await repo.mark_user_activated(user["id"])
    assert activated["status"] == "ACTIVE"
    assert activated["activated_at"] is not None
    assert activated["last_login_at"] is not None


async def _make_test_user(repo, email: str) -> dict:
    await repo.seed_rbac_defaults()
    role = await repo.get_role_by_name("VIEWER")
    org = await repo.create_organization(name=f"Org for {email}")
    return await repo.create_user(
        first_name="Test",
        last_name="User",
        email=email,
        organization_id=org["id"],
        role_id=role["id"],
        status="INVITED",
    )


async def test_magic_link_token_create_lookup_and_consume(repo):
    user = await _make_test_user(repo, "tokentest@example.com")
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    token = await repo.create_magic_link_token(
        user_id=user["id"],
        token_hash="a" * 64,
        purpose="INITIAL_INVITATION",
        expires_at=expires_at,
        requested_ip="127.0.0.1",
        user_agent="pytest",
    )
    assert token["consumed_at"] is None
    assert token["revoked_at"] is None

    found = await repo.get_magic_link_token_by_hash("a" * 64)
    assert found["id"] == token["id"]
    assert await repo.get_magic_link_token_by_hash("does-not-exist") is None

    consumed = await repo.consume_magic_link_token(token["id"])
    assert consumed["consumed_at"] is not None
    assert await repo.consume_magic_link_token("no-such-id") is None


async def test_revoke_unconsumed_magic_link_tokens_for_user_only_touches_matching_purpose(repo):
    user = await _make_test_user(repo, "revoketest@example.com")
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    invitation = await repo.create_magic_link_token(
        user_id=user["id"], token_hash="b" * 64, purpose="INITIAL_INVITATION", expires_at=expires_at
    )
    login = await repo.create_magic_link_token(
        user_id=user["id"], token_hash="c" * 64, purpose="LOGIN", expires_at=expires_at
    )

    revoked_count = await repo.revoke_unconsumed_magic_link_tokens_for_user(user["id"], purpose="INITIAL_INVITATION")
    assert revoked_count == 1

    invitation_after = await repo.get_magic_link_token_by_hash("b" * 64)
    login_after = await repo.get_magic_link_token_by_hash("c" * 64)
    assert invitation_after["id"] == invitation["id"] and invitation_after["revoked_at"] is not None
    assert login_after["id"] == login["id"] and login_after["revoked_at"] is None


async def test_session_create_get_list_and_revoke(repo):
    user = await _make_test_user(repo, "sessiontest@example.com")
    expires_at = datetime.now(timezone.utc) + timedelta(hours=8)
    session = await repo.create_session(
        user_id=user["id"], expires_at=expires_at, ip_address="10.0.0.1", user_agent="pytest-agent"
    )
    assert session["revoked_at"] is None

    fetched = await repo.get_session(session["id"])
    assert fetched == session
    assert await repo.get_session("no-such-session") is None

    listed = await repo.list_sessions_for_user(user["id"])
    assert [s["id"] for s in listed] == [session["id"]]

    revoked = await repo.revoke_session(session["id"])
    assert revoked["revoked_at"] is not None
    assert await repo.revoke_session("no-such-session") is None

    await repo.touch_session(session["id"])
    touched = await repo.get_session(session["id"])
    assert touched["last_seen_at"] >= session["last_seen_at"]


async def test_seed_feature_defaults_creates_the_full_catalog_and_role_grants(repo):
    await repo.seed_rbac_defaults()
    await repo.seed_feature_defaults()

    features = await repo.list_features()
    assert len(features) == 18
    keys = {f["key"] for f in features}
    assert "chief_trading_agent_chat" in keys
    assert "paper_trading" in keys

    sensitive = {f["key"] for f in features if f["security_sensitive"]}
    assert "chief_trading_agent_chat" in sensitive
    assert "market_dashboard" not in sensitive

    trader_role = await repo.get_role_by_name("TRADER")
    trader_features = await repo.get_role_feature_keys(trader_role["id"])
    assert "paper_trading" in trader_features
    assert "risk_analytics" not in trader_features


async def test_seed_feature_defaults_is_idempotent(repo):
    await repo.seed_rbac_defaults()
    await repo.seed_feature_defaults()
    first = await repo.list_features()
    await repo.seed_feature_defaults()
    second = await repo.list_features()
    assert len(first) == len(second) == 18


async def test_organization_and_user_feature_overrides_round_trip(repo):
    await repo.seed_rbac_defaults()
    await repo.seed_feature_defaults()
    role = await repo.get_role_by_name("VIEWER")
    org = await repo.create_organization(name="Feature Override Test Co")
    user = await repo.create_user(
        first_name="Override",
        last_name="Test",
        email="override.test@example.com",
        organization_id=org["id"],
        role_id=role["id"],
        status="ACTIVE",
    )

    assert await repo.get_organization_feature_overrides(org["id"]) == {}
    assert await repo.get_user_feature_overrides(user["id"]) == {}

    await repo.set_organization_feature_override(organization_id=org["id"], feature_key="data_export", enabled=False)
    assert await repo.get_organization_feature_overrides(org["id"]) == {"data_export": False}

    await repo.set_user_feature_override(user_id=user["id"], feature_key="data_export", enabled=True)
    assert await repo.get_user_feature_overrides(user["id"]) == {"data_export": True}

    # Setting again updates in place rather than duplicating a row.
    await repo.set_user_feature_override(user_id=user["id"], feature_key="data_export", enabled=False)
    assert await repo.get_user_feature_overrides(user["id"]) == {"data_export": False}

    with pytest.raises(ValueError):
        await repo.set_user_feature_override(user_id=user["id"], feature_key="not-a-real-feature", enabled=True)


async def test_chat_conversation_and_message_persistence(repo):
    conversation = await repo.create_chat_conversation(
        conversation_id="11111111-1111-1111-1111-111111111111", user_id="u-trader-1", organization_id=None
    )
    assert conversation["id"] == "11111111-1111-1111-1111-111111111111"

    fetched = await repo.get_chat_conversation(conversation["id"])
    assert fetched == conversation
    assert await repo.get_chat_conversation("does-not-exist") is None

    await repo.save_chat_message(conversation_id=conversation["id"], role="user", content="Why are we bullish?")
    await repo.save_chat_message(
        conversation_id=conversation["id"],
        role="assistant",
        content="Because of storage draws.",
        citations=[{"source": "trade_idea", "reference": "abc"}],
        freshness={"trade_created_at": "2024-01-01T00:00:00"},
        tool_used="why_bias",
        model="mock-llm",
        latency_ms=12.5,
        permissions_context={"roles": ["TRADER"], "permission_required": "trading_recommendations.view", "access_granted": True},
    )

    messages = await repo.list_chat_messages(conversation["id"])
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["tool_used"] == "why_bias"
    assert messages[1]["permissions_context"]["access_granted"] is True

    conversations = await repo.list_chat_conversations(user_id="u-trader-1")
    assert [c["id"] for c in conversations] == [conversation["id"]]
    assert await repo.list_chat_conversations(user_id="nobody") == []


async def test_get_permission_keys_for_role(repo):
    await repo.seed_rbac_defaults()
    trader_permissions = await repo.get_permission_keys_for_role("TRADER")
    assert "chief_agent.chat" in trader_permissions
    assert "admin.users.create" not in trader_permissions
    assert await repo.get_permission_keys_for_role("NOT_A_REAL_ROLE") == set()


async def test_set_feature_globally_enabled_toggles_and_rejects_unknown_key(repo):
    await repo.seed_feature_defaults()
    updated = await repo.set_feature_globally_enabled("paper_trading", False)
    assert updated["globally_enabled"] is False

    features = await repo.list_features()
    assert next(f for f in features if f["key"] == "paper_trading")["globally_enabled"] is False

    with pytest.raises(ValueError):
        await repo.set_feature_globally_enabled("not_a_real_feature", True)


async def test_set_role_feature_entitlement_toggles_grant(repo):
    await repo.seed_rbac_defaults()
    await repo.seed_feature_defaults()
    viewer = await repo.get_role_by_name("VIEWER")
    assert "paper_trading" not in await repo.get_role_feature_keys(viewer["id"])

    await repo.set_role_feature_entitlement(role_id=viewer["id"], feature_key="paper_trading", enabled=True)
    assert "paper_trading" in await repo.get_role_feature_keys(viewer["id"])

    await repo.set_role_feature_entitlement(role_id=viewer["id"], feature_key="paper_trading", enabled=False)
    assert "paper_trading" not in await repo.get_role_feature_keys(viewer["id"])

    with pytest.raises(ValueError):
        await repo.set_role_feature_entitlement(role_id=viewer["id"], feature_key="not_a_real_feature", enabled=True)


async def test_system_settings_seed_list_get_and_update_with_history(repo):
    await repo.seed_system_settings_defaults()
    settings = await repo.list_system_settings()
    keys = {s["key"] for s in settings}
    assert "platform_name" in keys
    assert "support_email" in keys
    assert "chat_defaults" in keys

    platform_name = await repo.get_system_setting("platform_name")
    assert platform_name["value"] == "AlphaGasIQ"
    assert platform_name["version"] == 1

    updated = await repo.set_system_setting("platform_name", "New Name", updated_by="u-admin-1")
    assert updated["value"] == "New Name"
    assert updated["version"] == 2
    assert updated["updated_by"] == "u-admin-1"

    history = await repo.list_system_setting_history("platform_name")
    assert len(history) == 1
    assert history[0]["value"] == "AlphaGasIQ"
    assert history[0]["version"] == 1

    assert await repo.get_system_setting("not_a_real_setting") is None
    with pytest.raises(ValueError):
        await repo.set_system_setting("not_a_real_setting", "x", updated_by=None)


async def test_seed_system_settings_defaults_is_idempotent(repo):
    await repo.seed_system_settings_defaults()
    await repo.set_system_setting("platform_name", "Customized Name", updated_by="admin")
    await repo.seed_system_settings_defaults()  # re-running must not revert the edit
    assert (await repo.get_system_setting("platform_name"))["value"] == "Customized Name"


async def test_update_user_profile_partial_update_and_missing_user(repo):
    await repo.seed_rbac_defaults()
    role = await repo.get_role_by_name("VIEWER")
    org = await repo.create_organization(name="Profile Edit Test Co")
    user = await repo.create_user(
        first_name="Before",
        last_name="Edit",
        email="profileedit@example.com",
        organization_id=org["id"],
        role_id=role["id"],
        status="ACTIVE",
    )

    updated = await repo.update_user_profile(user["id"], job_title="VP Trading")
    assert updated["job_title"] == "VP Trading"
    assert updated["first_name"] == "Before"  # untouched

    assert await repo.update_user_profile("no-such-user", job_title="x") is None


async def test_update_organization_partial_update_and_missing_org(repo):
    org = await repo.create_organization(name="Org Edit Test Co")
    updated = await repo.update_organization(org["id"], data_entitlements={"eia_full_history": True})
    assert updated["data_entitlements"] == {"eia_full_history": True}
    assert updated["name"] == "Org Edit Test Co"  # untouched

    assert await repo.update_organization("no-such-org", name="x") is None


async def test_seed_list_get_update_data_feed_configs(repo):
    await repo.seed_data_feed_configs(["eia", "noaa_nws"])
    configs = await repo.list_data_feed_configs()
    assert {c["provider_id"] for c in configs} == {"eia", "noaa_nws"}
    for c in configs:
        assert c["enabled"] is True
        assert c["paused"] is False
        assert c["priority"] == 100

    eia = await repo.get_data_feed_config("eia")
    assert eia["provider_id"] == "eia"
    assert await repo.get_data_feed_config("no-such-provider") is None

    updated = await repo.update_data_feed_config(
        "eia", paused=True, priority=10, notes="throttled during maintenance", updated_by="u-admin-1"
    )
    assert updated["paused"] is True
    assert updated["priority"] == 10
    assert updated["notes"] == "throttled during maintenance"
    assert updated["updated_by"] == "u-admin-1"
    assert updated["enabled"] is True  # untouched

    assert await repo.update_data_feed_config("no-such-provider", paused=True) is None


async def test_seed_data_feed_configs_is_idempotent(repo):
    await repo.seed_data_feed_configs(["eia"])
    await repo.update_data_feed_config("eia", notes="do not revert me")
    await repo.seed_data_feed_configs(["eia", "noaa_nws"])  # re-run with an added provider

    assert (await repo.get_data_feed_config("eia"))["notes"] == "do not revert me"
    assert await repo.get_data_feed_config("noaa_nws") is not None


async def test_record_and_list_data_feed_events(repo):
    await repo.seed_data_feed_configs(["eia"])
    await repo.record_data_feed_event(
        provider_id="eia", event_type="test_connection", status="success", detail="ok", latency_ms=12.5
    )
    event = await repo.record_data_feed_event(
        provider_id="eia",
        event_type="manual_refresh",
        status="success",
        detail="Fetched 3 observation(s).",
        records_received=3,
        latency_ms=42.0,
    )
    assert event["records_received"] == 3

    events = await repo.list_data_feed_events("eia")
    assert len(events) == 2
    assert events[0]["event_type"] == "manual_refresh"  # newest first

    assert await repo.list_data_feed_events("no-such-provider") == []


async def test_seed_list_get_update_agent_configs(repo):
    await repo.seed_agent_configs(["CHIEF_TRADING_AGENT", "SUPPLY"])
    configs = await repo.list_agent_configs()
    assert {c["agent_type"] for c in configs} == {"CHIEF_TRADING_AGENT", "SUPPLY"}
    for c in configs:
        assert c["status"] == "ACTIVE"

    chief = await repo.get_agent_config("CHIEF_TRADING_AGENT")
    assert chief["agent_type"] == "CHIEF_TRADING_AGENT"
    assert await repo.get_agent_config("NOT_A_REAL_AGENT") is None

    updated = await repo.update_agent_config(
        "SUPPLY", status="PAUSED", confidence_threshold=0.6, notes="paused for review", updated_by="u-admin-1"
    )
    assert updated["status"] == "PAUSED"
    assert updated["confidence_threshold"] == 0.6
    assert updated["notes"] == "paused for review"
    assert updated["updated_by"] == "u-admin-1"

    assert await repo.update_agent_config("NOT_A_REAL_AGENT", status="PAUSED") is None


async def test_seed_agent_configs_is_idempotent(repo):
    await repo.seed_agent_configs(["SUPPLY"])
    await repo.update_agent_config("SUPPLY", notes="do not revert me")
    await repo.seed_agent_configs(["SUPPLY", "DEMAND"])  # re-run with an added agent

    assert (await repo.get_agent_config("SUPPLY"))["notes"] == "do not revert me"
    assert await repo.get_agent_config("DEMAND") is not None
