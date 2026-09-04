"""tests/alpha/test_scenario_engine.py -- AlphaScenario(TM)'s composition/comparison
engine. Table-driven, mirroring test_consensus_engine.py's style. `ScenarioEngine.run()`
reuses `risk_service.scenarios.run_scenario` (already tested in tests/risk/), so these
tests focus on composition (`compose()`), the wrapping metadata (`run()`), and ranking
(`compare()`/`run_standing_library()`) -- not re-testing the underlying P&L math."""

from __future__ import annotations

import pytest
from alpha_service.scenario_engine import ScenarioEngine
from risk_service.metrics import PositionSnapshot
from risk_service.scenarios import SCENARIOS, get_scenario
from schemas import ScenarioDefinition, ScenarioFactorType, ScenarioVariable


@pytest.fixture
def engine() -> ScenarioEngine:
    return ScenarioEngine()


@pytest.fixture
def positions() -> list[PositionSnapshot]:
    return [
        PositionSnapshot(instrument="NG_M1", sector="NATURAL_GAS", quantity=100, price=3.0, avg_price=2.9, delta=1.0)
    ]


class TestCompose:
    def test_named_base_scenario_alone_reproduces_its_own_shocks(self, engine):
        base = get_scenario("freeport_lng_outage")
        composed = engine.compose(ScenarioDefinition(name="x", base_scenario_ids=["freeport_lng_outage"]))
        assert composed.price_shock_pct == pytest.approx(base.price_shock_pct)
        assert composed.demand_shock_bcf_d == pytest.approx(base.demand_shock_bcf_d)
        assert composed.volatility_multiplier == pytest.approx(base.volatility_multiplier)

    def test_custom_variable_alone(self, engine):
        composed = engine.compose(
            ScenarioDefinition(
                name="x", variables=[ScenarioVariable(factor_type=ScenarioFactorType.PRICE_SHOCK_PCT, value=0.2)]
            )
        )
        assert composed.price_shock_pct == pytest.approx(0.2)
        assert composed.demand_shock_bcf_d == 0.0
        assert composed.volatility_multiplier == pytest.approx(1.0)

    def test_price_demand_supply_shocks_stack_additively(self, engine):
        base = get_scenario("freeport_lng_outage")
        composed = engine.compose(
            ScenarioDefinition(
                name="x",
                base_scenario_ids=["freeport_lng_outage"],
                variables=[ScenarioVariable(factor_type=ScenarioFactorType.PRICE_SHOCK_PCT, value=0.10)],
            )
        )
        assert composed.price_shock_pct == pytest.approx(base.price_shock_pct + 0.10)

    def test_volatility_multipliers_compound_multiplicatively(self, engine):
        composed = engine.compose(
            ScenarioDefinition(
                name="x",
                variables=[ScenarioVariable(factor_type=ScenarioFactorType.VOLATILITY_MULTIPLIER, value=2.0)],
            )
        )
        assert composed.volatility_multiplier == pytest.approx(2.0)
        composed2 = engine.compose(
            ScenarioDefinition(
                name="x",
                base_scenario_ids=["major_hurricane"],  # volatility_multiplier=2.0
                variables=[ScenarioVariable(factor_type=ScenarioFactorType.VOLATILITY_MULTIPLIER, value=1.5)],
            )
        )
        assert composed2.volatility_multiplier == pytest.approx(3.0)

    def test_multiple_base_scenarios_stack(self, engine):
        a = get_scenario("freeport_lng_outage")
        b = get_scenario("pipeline_disruption")
        composed = engine.compose(
            ScenarioDefinition(name="x", base_scenario_ids=["freeport_lng_outage", "pipeline_disruption"])
        )
        assert composed.price_shock_pct == pytest.approx(a.price_shock_pct + b.price_shock_pct)
        assert composed.supply_shock_bcf_d == pytest.approx(a.supply_shock_bcf_d + b.supply_shock_bcf_d)

    def test_unknown_base_scenario_id_raises(self, engine):
        with pytest.raises(KeyError):
            engine.compose(ScenarioDefinition(name="x", base_scenario_ids=["does_not_exist"]))

    def test_empty_definition_is_a_zero_shock(self, engine):
        composed = engine.compose(ScenarioDefinition(name="no-op"))
        assert composed.price_shock_pct == 0.0
        assert composed.demand_shock_bcf_d == 0.0
        assert composed.supply_shock_bcf_d == 0.0
        assert composed.volatility_multiplier == pytest.approx(1.0)


class TestRun:
    def test_run_wraps_scenario_result_with_metadata(self, engine, positions):
        result = engine.run(
            ScenarioDefinition(name="Freeport", description="d", base_scenario_ids=["freeport_lng_outage"]),
            positions,
            organization_id="org-1",
            requested_by="user-1",
        )
        assert result.scenario_name == "Freeport"
        assert result.scenario_description == "d"
        assert result.base_scenario_ids == ["freeport_lng_outage"]
        assert result.organization_id == "org-1"
        assert result.requested_by == "user-1"
        assert result.portfolio_pnl != 0.0  # a real position exists, so the shock has an effect

    def test_run_reuses_risk_service_run_scenario_math(self, engine, positions):
        """The wrapped result's numbers must match calling risk_service.scenarios.run_scenario
        directly with the same composed scenario -- proving no shadow P&L math exists."""
        from risk_service.scenarios import run_scenario

        definition = ScenarioDefinition(name="Freeport", base_scenario_ids=["freeport_lng_outage"])
        composed = engine.compose(definition)
        direct = run_scenario(composed, positions)
        wrapped = engine.run(definition, positions)
        assert wrapped.portfolio_pnl == pytest.approx(direct.portfolio_pnl)
        assert wrapped.var_impact == pytest.approx(direct.var_impact)
        assert wrapped.largest_risk_contributor == direct.largest_risk_contributor


class TestCompareAndStandingLibrary:
    def test_compare_ranks_worst_to_best(self, engine, positions):
        results = [
            engine.run(ScenarioDefinition(name=s.name, base_scenario_ids=[s.scenario_id]), positions)
            for s in SCENARIOS
        ]
        comparison = engine.compare(results)
        pnls = [r.portfolio_pnl for r in results if r.scenario_name == comparison.worst_case_scenario_name]
        assert comparison.worst_case_portfolio_pnl == min(r.portfolio_pnl for r in results)
        assert comparison.best_case_portfolio_pnl == max(r.portfolio_pnl for r in results)
        assert len(comparison.ranked_scenario_names) == len(results)
        assert comparison.ranked_scenario_names[0] == comparison.worst_case_scenario_name
        assert comparison.ranked_scenario_names[-1] == comparison.best_case_scenario_name

    def test_compare_empty_list_returns_empty_comparison(self, engine):
        comparison = engine.compare([])
        assert comparison.run_ids == []
        assert comparison.worst_case_scenario_name == ""

    def test_run_standing_library_covers_every_scenario(self, engine, positions):
        results, comparison = engine.run_standing_library(positions)
        assert len(results) == len(SCENARIOS)
        assert {r.scenario_name for r in results} == {s.name for s in SCENARIOS}
        assert len(comparison.ranked_scenario_names) == len(SCENARIOS)
