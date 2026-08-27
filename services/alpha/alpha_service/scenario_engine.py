"""AlphaScenario(TM) (docs/alpha-intelligence.md section 7): composes named and/or
custom shocks into a single scenario, then reuses `risk_service.scenarios.run_scenario`
-- the already-tested P&L/VaR math -- rather than re-implementing it. Pure function,
no DB/LLM/event-bus access, same design philosophy as every other engine in this
package.

Milestone 4 is honest about scope: composition means summing/multiplying the four
existing shock dimensions (price/demand/supply/volatility) across every named base
scenario and custom `ScenarioVariable` supplied. There is no per-geography position
data or duration-decay model in this codebase, so `ScenarioVariable.geography`/
`asset_id`/`duration` are accepted but not yet used by `compose()` -- forward
compatibility with the full spec, not a claim that they're modeled today.
"""

from __future__ import annotations

from risk_service.metrics import PositionSnapshot
from risk_service.scenarios import SCENARIOS, Scenario, get_scenario, run_scenario
from schemas import (
    ScenarioComparison,
    ScenarioDefinition,
    ScenarioFactorType,
    ScenarioRunResult,
    ScenarioVariable,
)

_FACTOR_FIELD = {
    ScenarioFactorType.PRICE_SHOCK_PCT: "price_shock_pct",
    ScenarioFactorType.DEMAND_SHOCK_BCF_D: "demand_shock_bcf_d",
    ScenarioFactorType.SUPPLY_SHOCK_BCF_D: "supply_shock_bcf_d",
}


class ScenarioEngine:
    def compose(self, definition: ScenarioDefinition) -> Scenario:
        """Combines every named base scenario plus every custom variable into one
        `risk_service.scenarios.Scenario`. Price/demand/supply shocks are summed
        (additive stacking of independent shocks); volatility multipliers are
        multiplied (compounding uncertainty, matching AlphaImpact's decay
        philosophy of "never less uncertain by combining more shocks")."""
        price_shock_pct = 0.0
        demand_shock_bcf_d = 0.0
        supply_shock_bcf_d = 0.0
        volatility_multiplier = 1.0

        for base_id in definition.base_scenario_ids:
            base = get_scenario(base_id)
            price_shock_pct += base.price_shock_pct
            demand_shock_bcf_d += base.demand_shock_bcf_d
            supply_shock_bcf_d += base.supply_shock_bcf_d
            volatility_multiplier *= base.volatility_multiplier

        for variable in definition.variables:
            if variable.factor_type == ScenarioFactorType.PRICE_SHOCK_PCT:
                price_shock_pct += variable.value
            elif variable.factor_type == ScenarioFactorType.DEMAND_SHOCK_BCF_D:
                demand_shock_bcf_d += variable.value
            elif variable.factor_type == ScenarioFactorType.SUPPLY_SHOCK_BCF_D:
                supply_shock_bcf_d += variable.value
            elif variable.factor_type == ScenarioFactorType.VOLATILITY_MULTIPLIER:
                volatility_multiplier *= variable.value

        return Scenario(
            scenario_id=f"composed:{definition.id}",
            name=definition.name,
            description=definition.description,
            price_shock_pct=round(price_shock_pct, 6),
            demand_shock_bcf_d=round(demand_shock_bcf_d, 6),
            supply_shock_bcf_d=round(supply_shock_bcf_d, 6),
            volatility_multiplier=round(volatility_multiplier, 6),
        )

    def run(
        self,
        definition: ScenarioDefinition,
        positions: list[PositionSnapshot],
        *,
        organization_id: str | None = None,
        requested_by: str | None = None,
    ) -> ScenarioRunResult:
        scenario = self.compose(definition)
        result = run_scenario(scenario, positions)
        return ScenarioRunResult(
            organization_id=organization_id,
            scenario_name=definition.name,
            scenario_description=definition.description,
            base_scenario_ids=list(definition.base_scenario_ids),
            price_shock_pct=scenario.price_shock_pct,
            demand_shock_bcf_d=scenario.demand_shock_bcf_d,
            supply_shock_bcf_d=scenario.supply_shock_bcf_d,
            volatility_multiplier=scenario.volatility_multiplier,
            portfolio_pnl=result.portfolio_pnl,
            strategy_pnl=dict(result.strategy_pnl),
            margin_impact=result.margin_impact,
            var_impact=result.var_impact,
            largest_risk_contributor=result.largest_risk_contributor,
            requested_by=requested_by,
        )

    def run_standing_library(
        self,
        positions: list[PositionSnapshot],
        *,
        organization_id: str | None = None,
        requested_by: str | None = None,
    ) -> tuple[list[ScenarioRunResult], ScenarioComparison]:
        """Runs every scenario in `risk_service.scenarios.SCENARIOS` -- the
        continuously-maintained standing stress-test library -- against the same
        book in one pass and ranks the results worst-to-best by portfolio P&L
        impact."""
        results = [
            self.run(
                ScenarioDefinition(name=s.name, description=s.description, base_scenario_ids=[s.scenario_id]),
                positions,
                organization_id=organization_id,
                requested_by=requested_by,
            )
            for s in SCENARIOS
        ]
        return results, self.compare(results, organization_id=organization_id)

    def compare(
        self, results: list[ScenarioRunResult], *, organization_id: str | None = None
    ) -> ScenarioComparison:
        if not results:
            return ScenarioComparison(organization_id=organization_id)
        ranked = sorted(results, key=lambda r: r.portfolio_pnl)
        worst = ranked[0]
        best = ranked[-1]
        return ScenarioComparison(
            organization_id=organization_id,
            run_ids=[r.id for r in ranked],
            worst_case_scenario_name=worst.scenario_name,
            worst_case_portfolio_pnl=worst.portfolio_pnl,
            best_case_scenario_name=best.scenario_name,
            best_case_portfolio_pnl=best.portfolio_pnl,
            ranked_scenario_names=[r.scenario_name for r in ranked],
        )
