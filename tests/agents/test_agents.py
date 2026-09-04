from datetime import date

import pytest
from agent_sdk import MockLLMProvider
from agents_service import (
    BacktestingAgent,
    ChiefInvestmentAgent,
    ChiefTradingAgent,
    DemandAgent,
    ForecastingAgent,
    InvestmentCommittee,
    LNGAgent,
    PipelineAgent,
    PowerMarketAgent,
    RegimeDetectionAgent,
    RelativeValueAgent,
    StorageAgent,
    SupplyAgent,
    WeatherAgent,
)
from fundamentals_service.pipeline_graph import PipelineGraph, build_default_pipeline_graph
from fundamentals_service.seed import (
    generate_daily_balances,
    seed_lng_terminals,
    seed_power_markets,
    seed_storage_baseline,
)
from quant_service import generate_price_history
from schemas import AgentStatus, ForecastHorizon, RecommendedAction, RiskVerdict


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
async def test_pipeline_agent_reports_constrained_corridors():
    graph = build_default_pipeline_graph()
    agent = PipelineAgent(llm=MockLLMProvider())
    result = await agent.run(graph=graph)
    assert result.status == AgentStatus.SUCCESS
    assert result.outputs["constrained_corridor_count"] == len(graph.constrained_edges())
    assert result.outputs["total_capacity_bcf_d"] == graph.total_capacity_bcf_d()


@pytest.mark.asyncio
async def test_pipeline_agent_skips_on_empty_graph():
    agent = PipelineAgent(llm=MockLLMProvider())
    result = await agent.run(graph=PipelineGraph(nodes=[], edges=[]))
    assert result.status == AgentStatus.SKIPPED


@pytest.mark.asyncio
async def test_lng_agent_reports_utilization_and_netback():
    agent = LNGAgent(llm=MockLLMProvider())
    result = await agent.run(terminals=seed_lng_terminals(), henry_hub_price=3.0, ttf_price=12.0)
    assert result.status == AgentStatus.SUCCESS
    assert result.outputs["total_capacity_bcf_d"] > 0
    assert 0 <= result.outputs["average_utilization"] <= 1
    assert result.outputs["netback_ttf_usd_mmbtu"] is not None
    assert result.outputs["export_incentivized"] is True  # TTF far above HH + cost chain
    assert "Freeport" in result.outputs["terminals_in_maintenance"]


@pytest.mark.asyncio
async def test_lng_agent_skips_with_no_terminal_data():
    agent = LNGAgent(llm=MockLLMProvider())
    result = await agent.run(terminals=[], henry_hub_price=3.0)
    assert result.status == AgentStatus.SKIPPED


@pytest.mark.asyncio
async def test_lng_agent_reports_no_netback_without_ttf_price():
    agent = LNGAgent(llm=MockLLMProvider())
    result = await agent.run(terminals=seed_lng_terminals(), henry_hub_price=3.0, ttf_price=None)
    assert result.status == AgentStatus.SUCCESS
    assert result.outputs["netback_ttf_usd_mmbtu"] is None


@pytest.mark.asyncio
async def test_power_market_agent_reports_burn_estimate():
    agent = PowerMarketAgent(llm=MockLLMProvider())
    markets = seed_power_markets()
    result = await agent.run(markets=markets)
    assert result.status == AgentStatus.SUCCESS
    assert result.outputs["total_power_burn_bcf_d"] > 0
    assert set(result.outputs["burn_by_iso_bcf_d"]) == {m.iso for m in markets}


@pytest.mark.asyncio
async def test_power_market_agent_skips_with_no_market_data():
    agent = PowerMarketAgent(llm=MockLLMProvider())
    result = await agent.run(markets=[])
    assert result.status == AgentStatus.SKIPPED


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


@pytest.fixture
def price_history():
    return generate_price_history(end_date=date(2026, 8, 25), num_days=250)


@pytest.mark.asyncio
async def test_forecasting_agent_produces_price_forecast(price_history):
    prices = [o.value for o in sorted(price_history, key=lambda o: o.observation_time)]
    agent = ForecastingAgent(llm=MockLLMProvider())
    result = await agent.run(
        instrument="NGQ26", horizon=ForecastHorizon.SEVEN_DAY,
        training_prices=prices[-60:], current_price=prices[-1],
    )
    assert result.status == AgentStatus.SUCCESS
    assert "price_forecast" in result.outputs
    assert result.agent_id == "quant.forecasting.v1"


@pytest.mark.asyncio
async def test_forecasting_agent_skips_with_insufficient_history():
    agent = ForecastingAgent(llm=MockLLMProvider())
    result = await agent.run(instrument="NGQ26", horizon=ForecastHorizon.SEVEN_DAY, training_prices=[3.0], current_price=3.0)
    assert result.status == AgentStatus.SKIPPED


@pytest.mark.asyncio
async def test_regime_detection_agent_classifies_regime():
    agent = RegimeDetectionAgent(llm=MockLLMProvider())
    result = await agent.run(recent_returns=[0.01, -0.02, 0.015, -0.01, 0.02])
    assert result.status == AgentStatus.SUCCESS
    assert "regime" in result.outputs


@pytest.mark.asyncio
async def test_relative_value_agent_produces_both_signals():
    agent = RelativeValueAgent(llm=MockLLMProvider())
    result = await agent.run(henry_hub_price=2.5, ttf_price=9.5, m1_price=2.5, m2_price=2.6)
    assert result.status == AgentStatus.SUCCESS
    assert "hh_ttf_netback" in result.outputs
    assert "calendar_spread" in result.outputs


@pytest.mark.asyncio
async def test_backtesting_agent_compares_implemented_models(price_history):
    agent = BacktestingAgent(llm=MockLLMProvider())
    result = await agent.run(instrument="NGQ26", price_history=price_history, horizon=ForecastHorizon.SEVEN_DAY)
    assert result.status == AgentStatus.SUCCESS
    assert set(result.outputs["results_by_model"].keys()) == {
        "NAIVE_PERSISTENCE",
        "LINEAR_REGRESSION",
        "ARIMA",
        "VAR",
        "STATE_SPACE",
        "RANDOM_FOREST",
        "XGBOOST",
        "LIGHTGBM",
    }
    assert result.outputs["best_model"] in result.outputs["results_by_model"]


@pytest.mark.asyncio
async def test_backtesting_agent_skips_with_insufficient_history():
    agent = BacktestingAgent(llm=MockLLMProvider())
    short_history = generate_price_history(end_date=date(2026, 8, 25), num_days=10)
    result = await agent.run(instrument="NGQ26", price_history=short_history, horizon=ForecastHorizon.SEVEN_DAY)
    assert result.status == AgentStatus.SKIPPED


# -- admin disable/pause actually stops execution (docs/agent-governance.md §3) --------


@pytest.mark.asyncio
async def test_disabling_a_fundamental_agent_skips_it_without_running(balances):
    base = seed_storage_baseline(as_of=date(2026, 8, 25))
    cta = ChiefTradingAgent(llm=MockLLMProvider())
    result = await cta.run_research_cycle(
        instrument="NGZ26",
        current_price=3.0,
        balances=balances,
        five_year_average_bcf=base["five_year_average_bcf"],
        last_year_bcf=base["year_ago_inventory_bcf"],
        as_of=date(2026, 8, 25),
        weather_kwargs=dict(model="ECMWF", run="00z", comparison_run="12z", hdd_run=8.0, hdd_comparison=2.0, cdd_run=0.0, cdd_comparison=0.0),
        market_consensus_bcf=sum(b.balance_bcf for b in balances[-7:]) + 20,
        disabled_agent_types=frozenset({"SUPPLY"}),
    )
    assert result.supply.status == AgentStatus.SKIPPED
    assert result.supply.reasoning_summary == "Disabled by admin."
    assert result.supply.outputs == {}
    # everything else still ran normally
    assert result.demand.status == AgentStatus.SUCCESS


@pytest.mark.asyncio
async def test_disabling_the_directional_strategy_agent_prevents_any_trade_idea(balances):
    base = seed_storage_baseline(as_of=date(2026, 8, 25))
    cta = ChiefTradingAgent(llm=MockLLMProvider())
    result = await cta.run_research_cycle(
        instrument="NGZ26",
        current_price=3.0,
        balances=balances,
        five_year_average_bcf=base["five_year_average_bcf"],
        last_year_bcf=base["year_ago_inventory_bcf"],
        as_of=date(2026, 8, 25),
        weather_kwargs=dict(model="ECMWF", run="00z", comparison_run="12z", hdd_run=8.0, hdd_comparison=2.0, cdd_run=0.0, cdd_comparison=0.0),
        market_consensus_bcf=sum(b.balance_bcf for b in balances[-7:]) + 20,
        disabled_agent_types=frozenset({"DIRECTIONAL_STRATEGY"}),
    )
    assert result.strategy.status == AgentStatus.SKIPPED
    assert result.trade_ideas == []


@pytest.mark.asyncio
async def test_disabling_a_committee_member_forces_wait_for_more_data(balances):
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

    # Baseline: with full quorum this trade clears committee (consensus_score is high).
    baseline = await committee.deliberate(
        trade=trade, supporting_observations=[], freshness_limits_seconds={}, existing_positions={}
    )
    assert baseline.recommended_action != RecommendedAction.WAIT_FOR_MORE_DATA

    decision = await committee.deliberate(
        trade=trade,
        supporting_observations=[],
        freshness_limits_seconds={},
        existing_positions={},
        disabled_agent_types=frozenset({"BULL"}),
    )
    assert decision.recommended_action == RecommendedAction.WAIT_FOR_MORE_DATA
    assert any("quorum incomplete" in q for q in decision.unresolved_questions)
    # the disabled member's case is never fabricated
    assert decision.bull_case == "Disabled by admin."
    # the still-enabled members still ran for real
    assert decision.bear_case and decision.bear_case != "Disabled by admin."
