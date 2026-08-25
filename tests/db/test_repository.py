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
