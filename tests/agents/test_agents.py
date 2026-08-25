from datetime import date

import pytest
from agent_sdk import MockLLMProvider
from agents_service import (
    ChiefInvestmentAgent,
    ChiefTradingAgent,
    DemandAgent,
    InvestmentCommittee,
    StorageAgent,
    SupplyAgent,
    WeatherAgent,
)
from fundamentals_service.seed import generate_daily_balances, seed_storage_baseline
from schemas import AgentStatus, RecommendedAction, RiskVerdict


@pytest.fixture
def balances():
    return generate_daily_balances(end_date=date(2026, 8, 25), num_days=60)


@pytest.mark.asyncio
async def test_supply_agent_reports_success_with_data(balances):
    agent = SupplyAgent(llm=MockLLMProvider())
    result = await agent.run(balances=balances)
    assert result.status == AgentStatus.SUCCESS
    assert "avg_production_7d_bcf" in result.outputs
    assert result.agent_id == "fundamentals.supply.v1"
    assert result.errors == []


@pytest.mark.asyncio
async def test_supply_agent_skips_with_no_data():
    agent = SupplyAgent(llm=MockLLMProvider())
    result = await agent.run(balances=[])
    assert result.status == AgentStatus.SKIPPED


@pytest.mark.asyncio
async def test_demand_agent_reports_success(balances):
    agent = DemandAgent(llm=MockLLMProvider())
    result = await agent.run(balances=balances)
    assert result.status == AgentStatus.SUCCESS
    assert "avg_demand_7d_bcf" in result.outputs


@pytest.mark.asyncio
async def test_storage_agent_produces_forecast(balances):
    base = seed_storage_baseline(as_of=date(2026, 8, 25))
    agent = StorageAgent(llm=MockLLMProvider())
    result = await agent.run(
        balances=balances,
        five_year_average_bcf=base["five_year_average_bcf"],
        last_year_bcf=base["year_ago_inventory_bcf"],
        as_of=date(2026, 8, 25),
    )
    assert result.status == AgentStatus.SUCCESS
    assert "forecast_bcf" in result.outputs


@pytest.mark.asyncio
async def test_weather_agent_produces_impact():
    agent = WeatherAgent(llm=MockLLMProvider())
    result = await agent.run(
        model="ECMWF", run="00z", comparison_run="12z",
        hdd_run=5.0, hdd_comparison=2.0, cdd_run=0.0, cdd_comparison=0.0,
    )
    assert result.status == AgentStatus.SUCCESS
    assert result.outputs["price_direction"] == "BULLISH"


@pytest.mark.asyncio
async def test_agent_result_never_exposes_raw_chain_of_thought(balances):
    """AgentResult must only carry the distilled reasoning_summary field, never a
    'thoughts' or 'chain_of_thought' field — this is enforced by the schema shape
    itself, but we assert it here as a regression guard."""
    agent = SupplyAgent(llm=MockLLMProvider())
    result = await agent.run(balances=balances)
    dumped = result.model_dump()
    assert "chain_of_thought" not in dumped
    assert "thoughts" not in dumped
    assert "reasoning_summary" in dumped


@pytest.mark.asyncio
async def test_chief_trading_agent_full_cycle_produces_trade_idea(balances):
    base = seed_storage_baseline(as_of=date(2026, 8, 25))
    cta = ChiefTradingAgent(llm=MockLLMProvider())
    result = await cta.run_research_cycle(
        instrument="NGZ26",
        current_price=3.0,
        balances=balances,
        five_year_average_bcf=base["five_year_average_bcf"],
        last_year_bcf=base["year_ago_inventory_bcf"],
        as_of=date(2026, 8, 25),
        weather_kwargs=dict(
            model="ECMWF", run="00z", comparison_run="12z",
            hdd_run=8.0, hdd_comparison=2.0, cdd_run=0.0, cdd_comparison=0.0,
        ),
        market_consensus_bcf=sum(b.balance_bcf for b in balances[-7:]) + 20,
    )
    assert result.supply.status == AgentStatus.SUCCESS
    assert result.chief is not None
    # storage tighter than consensus + bullish weather -> should produce a trade idea
    assert len(result.trade_ideas) == 1
    assert result.trade_ideas[0].direction.value == "LONG"


@pytest.mark.asyncio
async def test_investment_committee_deliberates(balances):
    base = seed_storage_baseline(as_of=date(2026, 8, 25))
    cta = ChiefTradingAgent(llm=MockLLMProvider())
    result = await cta.run_research_cycle(
        instrument="NGZ26", current_price=3.0, balances=balances,
        five_year_average_bcf=base["five_year_average_bcf"], last_year_bcf=base["year_ago_inventory_bcf"],
        as_of=date(2026, 8, 25),
        weather_kwargs=dict(model="ECMWF", run="00z", comparison_run="12z", hdd_run=8.0, hdd_comparison=2.0, cdd_run=0.0, cdd_comparison=0.0),
        market_consensus_bcf=sum(b.balance_bcf for b in balances[-7:]) + 20,
    )
    trade = result.trade_ideas[0]
    committee = InvestmentCommittee(llm=MockLLMProvider())
    decision = await committee.deliberate(
        trade=trade, supporting_observations=[], freshness_limits_seconds={}, existing_positions={}
    )
    assert decision.recommended_action in RecommendedAction
    assert decision.bull_case
    assert decision.bear_case


@pytest.mark.asyncio
async def test_chief_investment_agent_never_forwards_when_risk_blocks():
    from schemas import Direction, InstrumentType, InvestmentCommitteeDecision, TradeIdea

    trade = TradeIdea(
        strategy="test", instrument="NGZ26", instrument_type=InstrumentType.FUTURE,
        direction=Direction.LONG, entry=3.0, target=3.5, stop_or_invalidation=2.8,
        time_horizon="1W", expected_return=100, expected_loss=50, probability_success=0.8,
        confidence=0.8, thesis="t",
    )
    decision = InvestmentCommitteeDecision(
        original_trade=trade, bull_case="b", bear_case="b", skeptic_case="s",
        data_quality_assessment="ok", portfolio_effect="ok", consensus_score=0.9,
        recommended_action=RecommendedAction.APPROVE_FOR_REVIEW,
    )
    cia = ChiefInvestmentAgent(llm=MockLLMProvider())

    for blocking_verdict in (RiskVerdict.BLOCK, RiskVerdict.HALT, RiskVerdict.REJECT, RiskVerdict.BLOCK_NEW_RISK):
        result = await cia.run(committee_decision=decision, risk_verdict=blocking_verdict)
        assert result.outputs["forward_for_human_review"] is False

    allowed = await cia.run(committee_decision=decision, risk_verdict=RiskVerdict.ALLOW)
    assert allowed.outputs["forward_for_human_review"] is True
