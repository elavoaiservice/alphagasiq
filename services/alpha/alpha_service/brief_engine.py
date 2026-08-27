"""The Overnight Intelligence Brief (docs/alpha-intelligence.md section 10,
Milestone 7): a single cross-component digest of what AlphaSignal, AlphaImpact,
AlphaConsensus, AlphaScenario, and AlphaMemory each concluded over a period.
`BriefEngine.compose()` is pure -- it never queries anything itself, only
selects/ranks/summarizes already-computed, already-persisted records the caller
hands it (`AppState.generate_intelligence_brief()` owns fetching those). Its
`headline`/`summary` are composed from fixed templates, not an LLM -- the same
"no LLM in the engine path" discipline as `MaterialityEngine`/`ImpactEngine`/
`ConsensusEngine`/`ScenarioEngine`/`LessonEngine`."""

from __future__ import annotations

from datetime import datetime

from schemas import (
    ConsensusView,
    ImpactAnalysis,
    IntelligenceBrief,
    LessonProposal,
    LessonProposalStatus,
    ScenarioRunResult,
    Signal,
)


class BriefEngine:
    def compose(
        self,
        *,
        market: str,
        period_start: datetime,
        period_end: datetime,
        signals: list[Signal],
        impacts: list[ImpactAnalysis],
        consensus_views: list[ConsensusView],
        scenario_runs: list[ScenarioRunResult],
        lesson_proposals: list[LessonProposal],
        organization_id: str | None = None,
        top_n: int = 5,
    ) -> IntelligenceBrief:
        top_signals = sorted(signals, key=lambda s: s.materiality_score, reverse=True)[:top_n]
        top_signal_ids = {s.id for s in top_signals}
        top_impacts = [i for i in impacts if i.signal_id in top_signal_ids][:top_n]
        consensus_highlights = sorted(consensus_views, key=lambda v: v.dispersion, reverse=True)[:top_n]
        # Worst-case first -- the scenarios most worth a trader's attention.
        notable_scenario_runs = sorted(scenario_runs, key=lambda r: r.portfolio_pnl)[:top_n]
        pending_lessons = [lp for lp in lesson_proposals if lp.status == LessonProposalStatus.PENDING][:top_n]

        return IntelligenceBrief(
            organization_id=organization_id,
            market=market,
            period_start=period_start,
            period_end=period_end,
            headline=self._headline(top_signals, consensus_highlights),
            summary=self._summary(top_signals, top_impacts, consensus_highlights, notable_scenario_runs, pending_lessons),
            top_signals=top_signals,
            top_impacts=top_impacts,
            consensus_highlights=consensus_highlights,
            notable_scenario_runs=notable_scenario_runs,
            pending_lessons=pending_lessons,
        )

    def _headline(self, top_signals: list[Signal], consensus_highlights: list[ConsensusView]) -> str:
        if top_signals:
            lead = top_signals[0]
            return f"{lead.signal_type.value}: {lead.headline}"
        if consensus_highlights:
            view = consensus_highlights[0]
            return f"AlphaConsensus: {view.agreement_label} agreement on {view.market} {view.target}"
        return "No material signals or consensus divergence in this period."

    def _summary(
        self,
        top_signals: list[Signal],
        top_impacts: list[ImpactAnalysis],
        consensus_highlights: list[ConsensusView],
        notable_scenario_runs: list[ScenarioRunResult],
        pending_lessons: list[LessonProposal],
    ) -> str:
        parts = [
            f"{len(top_signals)} material signal(s) detected." if top_signals else "No material signals detected."
        ]
        if top_impacts:
            parts.append(f"{len(top_impacts)} impact analysis(es) available.")
        if consensus_highlights:
            parts.append(f"{len(consensus_highlights)} consensus view(s) computed.")
        if notable_scenario_runs:
            worst = notable_scenario_runs[0]
            parts.append(f"Worst recent scenario: '{worst.scenario_name}' ({worst.portfolio_pnl:+.2f}).")
        if pending_lessons:
            parts.append(f"{len(pending_lessons)} lesson proposal(s) awaiting human review.")
        return " ".join(parts)
