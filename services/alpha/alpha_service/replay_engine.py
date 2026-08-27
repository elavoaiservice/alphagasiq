"""AlphaReplay(TM) (docs/alpha-intelligence.md section 9): assembles an
`AsOfReplayResult` from already-fetched, already-as-of-filtered data. Pure -- no
DB/LLM/event-bus access, same design philosophy as every other engine in this
package. All of the actual bitemporal correctness (the "as known at" filtering
that prevents look-ahead bias) happens in the repository layer --
`SqlAppRepository.list_market_observations_as_of()` and the `until`/`market`
parameters on `list_signals`/`list_impact_analyses`/`list_consensus_views`/
`list_scenario_runs`/`list_memory_records` -- so there is exactly one place
look-ahead bias could be introduced (those queries), not two. This engine only
packages already-correct results into the response shape.
"""

from __future__ import annotations

from datetime import datetime

from schemas import (
    AsOfReplayResult,
    ConsensusView,
    ImpactAnalysis,
    MemoryRecord,
    ScenarioRunResult,
    Signal,
    TimeSeriesObservation,
)


class ReplayEngine:
    def assemble(
        self,
        *,
        market: str,
        as_of: datetime,
        price_observations: list[TimeSeriesObservation],
        signals: list[Signal],
        impacts: list[ImpactAnalysis],
        consensus_views: list[ConsensusView],
        scenario_runs: list[ScenarioRunResult],
        memory_records: list[MemoryRecord],
    ) -> AsOfReplayResult:
        return AsOfReplayResult(
            market=market,
            as_of=as_of,
            price_observations=price_observations,
            signals=signals,
            impacts=impacts,
            consensus_views=consensus_views,
            scenario_runs=scenario_runs,
            memory_records=memory_records,
        )
