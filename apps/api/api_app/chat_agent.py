"""AI Trader Chat: answers questions using tools that retrieve real platform data —
never hallucinated values. Every answer carries citations, source, and freshness.

The tool router below is intentionally simple keyword matching rather than a full LLM
tool-use loop, so the chat is fully useful even when `ANTHROPIC_API_KEY` is not set
(`MockLLMProvider` cannot itself invoke tools). When a real Claude key is configured,
the retrieved facts are handed to the LLM to phrase into prose; the underlying numbers
always come from `AppState`, never from the model.

Milestone 5 (docs/access-model.md §6, spec §§26-28) adds server-side tool
authorization: `ask()` now takes the requesting `User` and checks their effective
permissions *before* invoking a tool — never after, and never delegated to the LLM
(which cannot be trusted to enforce access control on itself). `_TOOL_PERMISSIONS`
maps each topic to the permission it requires; an ungranted permission short-circuits
straight to a declined-access message without ever touching `AppState`'s real data.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from agent_sdk import LLMMessage, LLMProvider
from alpha_service import ScenarioEngine
from risk_service.metrics import PositionSnapshot
from risk_service.scenarios import get_scenario, run_scenario
from schemas import ScenarioDefinition, ScenarioFactorType, ScenarioVariable

from .auth import User
from .entitlements import get_effective_permissions
from .state import AppState


_UP_WORDS = ("up", "spike", "spikes", "higher", "rally", "rallies", "rise", "rises", "increase")
_DOWN_WORDS = ("down", "drop", "drops", "lower", "collapse", "collapses", "fall", "falls", "decrease", "decline")
_ISO_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})(?:[t ](\d{2}:\d{2}(?::\d{2})?))?")


def _extract_price_shock_pct(q: str) -> float | None:
    """Regex-based extraction of an explicit percentage price move plus a direction
    word (e.g. "prices spike 20%" -> +0.20, "prices drop 15%" -> -0.15) for
    `ChatAgent._run_named_scenario`'s scenario composition. Returns `None` if no
    percentage is present, or if a percentage is present without any recognizable
    direction word -- this is deliberately not a general NLU parser, so an
    ambiguous phrasing is left unparsed rather than guessing a sign."""
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", q)
    if match is None:
        return None
    magnitude = float(match.group(1)) / 100.0
    if any(word in q for word in _DOWN_WORDS):
        return -magnitude
    if any(word in q for word in _UP_WORDS):
        return magnitude
    return None


class ToolResult:
    def __init__(self, content: str, citations: list[dict[str, Any]], freshness: dict[str, Any]):
        self.content = content
        self.citations = citations
        self.freshness = freshness
        # Populated by `ChatAgent.ask()` after dispatch — never set by an individual
        # tool method, so no existing internal call site needs to change.
        self.tool_used: str | None = None
        self.model: str | None = None
        self.latency_ms: float | None = None
        self.permission_required: str | None = None
        self.access_granted: bool = True


# Each chat topic's required permission (spec §28 "Chat Authorization" — e.g. a
# question that reads portfolio positions/P&L requires `portfolio.view`, matching
# the spec's own example: "User without portfolio access: Cannot retrieve restricted
# portfolio data"). `VIEWER` (and therefore an anonymous/unauthenticated caller, who
# is treated as VIEWER — see `auth.py::_ANONYMOUS_USER`) has every permission below
# except `portfolio.view`, so general market-intelligence questions stay open exactly
# as before this milestone while portfolio/scenario questions now require it.
_TOOL_PERMISSIONS: dict[str, str] = {
    "why_bias": "trading_recommendations.view",
    "what_invalidates": "trading_recommendations.view",
    "most_disagreeing_agent": "trading_recommendations.view",
    "hdd_sensitivity": "weather.view",
    "weather_run_delta": "weather.view",
    "run_named_scenario": "portfolio.view",
    "show_evidence": "trading_recommendations.view",
    "compare_forecast_vs_consensus": "storage.view",
    "top_risks": "portfolio.view",
    "what_changed_overnight": "alpha_signals.view",
    "why_does_it_matter": "alpha_impacts.view",
    "agent_consensus": "alpha_consensus.view",
    "scenario_comparison": "alpha_scenarios.view",
    "decision_memory": "alpha_memory.view",
    "replay_snapshot": "alpha_replay.view",
    "overnight_brief": "alpha_brief.view",
    "what_changed": "dashboard.view",
    "todays_move": "news.view",
    "general_status": "dashboard.view",
}


class ChatAgent:
    def __init__(self, llm: LLMProvider):
        self.llm = llm

    def _route(self, q: str) -> str:
        if "invalidate" in q:
            return "what_invalidates"
        elif "disagree" in q:
            return "most_disagreeing_agent"
        elif "sensitiv" in q and "hdd" in q:
            return "hdd_sensitivity"
        elif "ecmwf" in q or ("weather" in q and ("run" in q or "model" in q)):
            return "weather_run_delta"
        elif "compare scenario" in q or "every scenario" in q or "stress test" in q or "standing library" in q:
            return "scenario_comparison"
        elif "scenario" in q or "freeport" in q or "offline" in q:
            return "run_named_scenario"
        elif "evidence" in q or "data point" in q or "show every" in q:
            return "show_evidence"
        elif "consensus" in q and ("eia" in q or "storage" in q):
            return "compare_forecast_vs_consensus"
        elif "largest risk" in q or "biggest risk" in q or "risk in the portfolio" in q:
            return "top_risks"
        elif "why does it matter" in q or "why does that matter" in q or "why is that important" in q or "why is this important" in q or "alphaimpact" in q:
            return "why_does_it_matter"
        elif "overnight brief" in q or "morning brief" in q or "daily brief" in q or "intelligence brief" in q:
            return "overnight_brief"
        elif "overnight" in q or "material change" in q or "alphasignal" in q:
            return "what_changed_overnight"
        elif "agree" in q or "alphaconsensus" in q or "agent alpha score" in q or "do the agents" in q:
            return "agent_consensus"
        elif "what have we learned" in q or "lesson" in q or "past decision" in q or "alphamemory" in q or "decision memory" in q:
            return "decision_memory"
        elif "time machine" in q or "what did we know" in q or "as of" in q or "alphareplay" in q or "replay" in q:
            return "replay_snapshot"
        elif "what changed" in q or "last six hours" in q or "recent" in q:
            return "what_changed"
        elif "caused today" in q or "today's move" in q or "why did" in q and "move" in q:
            return "todays_move"
        elif "why are we" in q or "why bullish" in q or "why bearish" in q or "argue" in q or "arguments against" in q:
            return "why_bias"
        else:
            return "general_status"

    async def _dispatch(self, topic: str, q: str, state: AppState) -> ToolResult:
        if topic == "what_invalidates":
            return self._what_invalidates(q, state)
        elif topic == "most_disagreeing_agent":
            return self._most_disagreeing_agent(state)
        elif topic == "hdd_sensitivity":
            return self._hdd_sensitivity(q, state)
        elif topic == "weather_run_delta":
            return self._weather_run_delta(state)
        elif topic == "run_named_scenario":
            return self._run_named_scenario(q, state)
        elif topic == "show_evidence":
            return self._show_evidence(q, state)
        elif topic == "compare_forecast_vs_consensus":
            return self._compare_forecast_vs_consensus(state)
        elif topic == "top_risks":
            return self._top_risks(state)
        elif topic == "why_does_it_matter":
            return self._why_does_it_matter(state)
        elif topic == "what_changed_overnight":
            return self._what_changed_overnight(state)
        elif topic == "agent_consensus":
            return self._agent_consensus_view(state)
        elif topic == "scenario_comparison":
            return self._scenario_comparison(state)
        elif topic == "decision_memory":
            return self._decision_memory(state)
        elif topic == "replay_snapshot":
            return await self._replay_snapshot(q, state)
        elif topic == "overnight_brief":
            return self._overnight_brief(state)
        elif topic == "what_changed":
            return self._what_changed(q, state)
        elif topic == "todays_move":
            return self._todays_move(state)
        elif topic == "why_bias":
            return self._why_bias(q, state)
        else:
            return self._general_status(state)

    async def ask(self, question: str, state: AppState, user: User) -> ToolResult:
        q = question.lower()
        topic = self._route(q)
        required_permission = _TOOL_PERMISSIONS[topic]

        start = time.perf_counter()
        permissions = await get_effective_permissions(user, state)
        access_granted = required_permission in permissions

        if not access_granted:
            # Declined before any tool ever touches AppState's real data — this *is*
            # the server-side enforcement point spec §28 requires; the LLM is never
            # consulted and never gets a chance to talk its way past it.
            result = ToolResult(
                f"I can't share that — it requires the '{required_permission}' permission, which "
                "your account doesn't currently have. Contact your administrator if you believe "
                "this is incorrect.",
                [],
                {},
            )
            model_used = None
        else:
            result = await self._dispatch(topic, q, state)
            prompt = (
                "You are the AlphaGasIQ AI Trader Chat assistant. Using ONLY the facts below "
                "(never invent numbers), answer the trader's question concisely and professionally.\n\n"
                f"Question: {question}\n\nFacts:\n{result.content}"
            )
            llm_response = await self.llm.complete([LLMMessage(role="user", content=prompt)], max_tokens=400)
            content = result.content if "MOCK LLM RESPONSE" in llm_response.content else llm_response.content
            model_used = llm_response.model
            result = ToolResult(content=content, citations=result.citations, freshness=result.freshness)

        result.tool_used = topic
        result.model = model_used
        result.latency_ms = (time.perf_counter() - start) * 1000
        result.permission_required = required_permission
        result.access_granted = access_granted
        return result

    # -- tools -------------------------------------------------------------

    def _why_bias(self, q: str, state: AppState) -> ToolResult:
        if not state.trade_ideas:
            return ToolResult("No active trade ideas at the moment.", [], {})
        trade = list(state.trade_ideas.values())[-1]
        decision = state.committee_decisions.get(trade.trade_id)
        lines = [f"Latest trade idea: {trade.direction.value} {trade.instrument} — {trade.thesis}"]
        if "argument" in q and "against" in q:
            if decision:
                lines.append(f"Strongest counter-arguments (Bear case): {decision.bear_case}")
                lines.append(f"Skeptic case: {decision.skeptic_case}")
            lines.append("Stated risks: " + "; ".join(trade.risks))
        else:
            lines.append("Catalysts: " + "; ".join(trade.catalysts))
            if decision:
                lines.append(f"Bull case: {decision.bull_case}")
        return ToolResult(
            "\n".join(lines),
            [{"source": "trade_idea", "reference": str(trade.trade_id)}],
            {"trade_created_at": trade.created_at.isoformat()},
        )

    def _what_invalidates(self, q: str, state: AppState) -> ToolResult:
        if not state.trade_ideas:
            return ToolResult("No active trade ideas.", [], {})
        trade = list(state.trade_ideas.values())[-1]
        content = (
            f"Invalidation conditions for {trade.instrument}: " + "; ".join(trade.invalidation_conditions)
            + f". Stop/invalidation level: {trade.stop_or_invalidation}."
        )
        return ToolResult(content, [{"source": "trade_idea", "reference": str(trade.trade_id)}], {})

    def _most_disagreeing_agent(self, state: AppState) -> ToolResult:
        if not state.committee_decisions:
            return ToolResult("No committee deliberations recorded yet.", [], {})
        decision = list(state.committee_decisions.values())[-1]
        content = (
            f"Bear Agent shows the strongest disagreement with the primary thesis: {decision.bear_case} "
            f"Skeptic Agent raised: {decision.skeptic_case}"
        )
        return ToolResult(content, [{"source": "investment_committee", "reference": str(decision.original_trade.trade_id)}], {})

    def _hdd_sensitivity(self, q: str, state: AppState) -> ToolResult:
        match = re.search(r"(-?\d+(\.\d+)?)\s*hdd", q)
        hdd_delta = float(match.group(1)) if match else -10.0
        from fundamentals_service.weather_impact import DEFAULT_RESCOM_BCF_PER_HDD

        demand_delta = hdd_delta * DEFAULT_RESCOM_BCF_PER_HDD
        content = (
            f"A {hdd_delta:+.0f} HDD change is estimated to shift res/comm demand by "
            f"{demand_delta:+.2f} Bcf/d (using {DEFAULT_RESCOM_BCF_PER_HDD} Bcf/d per HDD, "
            "the platform's current calibrated sensitivity). Portfolio-level price sensitivity "
            "translation is not yet wired to a formal factor model (Quantitative Team backlog)."
        )
        return ToolResult(content, [{"source": "fundamentals_service.weather_impact", "reference": "DEFAULT_RESCOM_BCF_PER_HDD"}], {})

    def _weather_run_delta(self, state: AppState) -> ToolResult:
        weather_results = [r for r in state.agent_execution_log if r.agent_type.value == "WEATHER"]
        if not weather_results:
            return ToolResult("No weather model runs recorded yet.", [], {})
        latest = weather_results[-1]
        content = (
            f"{latest.outputs.get('model')} {latest.outputs.get('run')} vs "
            f"{latest.outputs.get('comparison_run')}: HDD delta {latest.outputs.get('hdd_delta'):+.2f}, "
            f"CDD delta {latest.outputs.get('cdd_delta'):+.2f}, total demand delta "
            f"{latest.outputs.get('total_demand_delta_bcf'):+.2f} Bcf/d "
            f"({latest.outputs.get('price_direction')})."
        )
        return ToolResult(
            content,
            [c.model_dump(mode="json") for c in latest.citations],
            {"last_execution_time": latest.last_execution_time.isoformat()},
        )

    def _run_named_scenario(self, q: str, state: AppState) -> ToolResult:
        scenario_id = None
        if "freeport" in q or "lng" in q and "offline" in q:
            scenario_id = "freeport_lng_outage"
        else:
            for candidate in ("polar_vortex", "hurricane", "pipeline_disruption"):
                if candidate.split("_")[0] in q:
                    scenario_id = candidate
                    break
        scenario_id = scenario_id or "freeport_lng_outage"
        try:
            scenario = get_scenario(scenario_id)
        except KeyError:
            return ToolResult(f"Unknown scenario '{scenario_id}'.", [], {})

        # AlphaScenario(TM) (docs/alpha-intelligence.md section 7): if the question
        # also names an explicit percentage price move ("...and prices spike 20%"),
        # stack it onto the matched named scenario via `ScenarioEngine.compose()`
        # instead of only ever running the named scenario alone -- a modest, honest
        # slice of "natural-language-to-scenario parsing": regex extraction of an
        # explicit number + direction word, not a general NLU parser.
        price_shock_pct = _extract_price_shock_pct(q)
        variables = (
            [ScenarioVariable(factor_type=ScenarioFactorType.PRICE_SHOCK_PCT, value=price_shock_pct)]
            if price_shock_pct is not None
            else []
        )
        composed = ScenarioEngine().compose(
            ScenarioDefinition(name=scenario.name, description=scenario.description, base_scenario_ids=[scenario_id], variables=variables)
        )

        positions = [
            PositionSnapshot(
                instrument=instrument,
                sector="NATURAL_GAS",
                quantity=pos.quantity,
                price=state.mark_price(instrument),
                avg_price=pos.avg_price,
            )
            for instrument, pos in state.paper_adapter.portfolio.positions.items()
        ]
        result = run_scenario(composed, positions)
        composition_note = f" plus a {price_shock_pct:+.0%} price shock" if price_shock_pct is not None else ""
        content = (
            f"Scenario '{scenario.name}'{composition_note}: portfolio P&L impact {result.portfolio_pnl:+.2f}, "
            f"VaR impact {result.var_impact:+.2f}, margin impact {result.margin_impact:.2f}, "
            f"largest risk contributor: {result.largest_risk_contributor}."
        )
        return ToolResult(content, [{"source": "risk_service.scenarios", "reference": scenario_id}], {})

    def _scenario_comparison(self, state: AppState) -> ToolResult:
        """AlphaScenarioTool (docs/alpha-intelligence.md section 43/7) -- runs the
        entire standing stress-test library against the current paper book in one
        pass and ranks the results, the "base vs. A vs. B vs. C" comparison. Calls
        `state.alpha_scenario_engine` directly (a pure, synchronous engine call, no
        persistence) rather than `state.run_alpha_scenario_comparison()`, matching
        this project's established provisional decision to keep the chat dispatch
        path synchronous rather than making it async-aware for one topic."""
        positions = [
            PositionSnapshot(
                instrument=instrument,
                sector="NATURAL_GAS",
                quantity=pos.quantity,
                price=state.mark_price(instrument),
                avg_price=pos.avg_price,
            )
            for instrument, pos in state.paper_adapter.portfolio.positions.items()
        ]
        results, comparison = state.alpha_scenario_engine.run_standing_library(positions)
        content = (
            f"Ran all {len(results)} scenarios in the standing stress-test library. "
            f"Worst case: '{comparison.worst_case_scenario_name}' ({comparison.worst_case_portfolio_pnl:+.2f}). "
            f"Best case: '{comparison.best_case_scenario_name}' ({comparison.best_case_portfolio_pnl:+.2f})."
        )
        return ToolResult(content, [{"source": "risk_service.scenarios", "reference": "SCENARIOS"}], {"scenario_count": len(results)})

    def _decision_memory(self, state: AppState) -> ToolResult:
        """AlphaMemoryTool (docs/alpha-intelligence.md section 43/8) -- surfaces the
        most recent closed-trade decision memories and any still-pending lesson
        proposals drafted from them. Reads `state.recent_memory_records`/
        `recent_lesson_proposals`, the same bounded in-memory cache pattern every
        other Alpha* chat topic uses."""
        if not state.recent_memory_records:
            return ToolResult("No decision memory recorded yet -- nothing has closed with a lesson to report.", [], {})
        top = state.recent_memory_records[-5:]
        lines = [f"[{m.outcome_quadrant.value if m.outcome_quadrant else 'UNRESOLVED'}] {m.title}: {m.summary}" for m in reversed(top)]
        pending = [lp for lp in state.recent_lesson_proposals if lp.status.value == "PENDING"]
        if pending:
            lines.append(f"{len(pending)} lesson proposal(s) awaiting human review.")
        return ToolResult(
            "\n".join(lines),
            [{"source": "alpha_service.memory_builder", "reference": str(m.id)} for m in top],
            {"memory_count": len(state.recent_memory_records), "pending_lessons": len(pending)},
        )

    async def _replay_snapshot(self, q: str, state: AppState) -> ToolResult:
        """AlphaReplayTool (docs/alpha-intelligence.md section 43/9) -- reconstructs
        what the Alpha Intelligence Layer itself knew and concluded as of a chosen
        moment. Parses an explicit `YYYY-MM-DD[ HH:MM[:SS]]` from the question if
        present, defaulting to now otherwise -- this is not a general date-NLU
        parser, so a relative phrase like "last Tuesday" is left unparsed rather
        than guessed. This is the first Alpha* chat topic whose answer cannot come
        from a bounded in-memory cache (it needs an arbitrary-timestamp bitemporal
        query), so unlike every other topic method here it directly awaits
        `state.compute_as_of_replay()` rather than reading `state.recent_*`."""
        match = _ISO_DATE_RE.search(q)
        as_of = datetime.now(timezone.utc)
        if match:
            date_part = match.group(1)
            time_part = match.group(2) or "00:00:00"
            try:
                as_of = datetime.fromisoformat(f"{date_part}T{time_part}").replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        result = await state.compute_as_of_replay(as_of=as_of, organization_id=None)
        content = (
            f"As of {as_of.isoformat()}, the Alpha Intelligence Layer had recorded: "
            f"{len(result.price_observations)} price observation(s), {len(result.signals)} signal(s), "
            f"{len(result.impacts)} impact analysis(es), {len(result.consensus_views)} consensus view(s), "
            f"{len(result.scenario_runs)} scenario run(s), {len(result.memory_records)} decision memory "
            f"record(s). Mode: {result.mode.value} -- a replay of what this already-running system itself "
            "knew at that moment, not a reconstruction of market reality from before AlphaReplay's "
            "bitemporal store existed."
        )
        return ToolResult(
            content,
            [{"source": "alpha_service.replay_engine", "reference": as_of.isoformat()}],
            {"as_of": as_of.isoformat(), "mode": result.mode.value},
        )

    def _overnight_brief(self, state: AppState) -> ToolResult:
        """The Overnight Intelligence Brief chat topic (docs/alpha-intelligence.md
        section 10, Milestone 7) -- reads `state.recent_briefs`, the same bounded
        in-memory cache pattern every other Alpha* topic (except AlphaReplay's
        arbitrary-timestamp query) uses. A brief is only generated once per full
        research cycle, so this simply reports the latest one rather than
        recomputing anything."""
        if not state.recent_briefs:
            return ToolResult("No Overnight Intelligence Brief has been generated yet.", [], {})
        brief = state.recent_briefs[-1]
        content = f"{brief.headline} {brief.summary}"
        return ToolResult(
            content,
            [{"source": "alpha_service.brief_engine", "reference": str(brief.id)}],
            {
                "generated_at": brief.generated_at.isoformat(),
                "period_start": brief.period_start.isoformat(),
                "period_end": brief.period_end.isoformat(),
            },
        )

    def _show_evidence(self, q: str, state: AppState) -> ToolResult:
        if not state.trade_ideas:
            return ToolResult("No active trade ideas.", [], {})
        trade = list(state.trade_ideas.values())[-1]
        content = (
            f"Supporting data for {trade.instrument}: {', '.join(trade.supporting_data)}. "
            f"Source citations: {', '.join(trade.source_citations)}."
        )
        return ToolResult(
            content,
            [{"source": s, "reference": s} for s in trade.source_citations],
            {"trade_created_at": trade.created_at.isoformat()},
        )

    def _compare_forecast_vs_consensus(self, state: AppState) -> ToolResult:
        storage_results = [r for r in state.agent_execution_log if r.agent_type.value == "STORAGE"]
        if not storage_results:
            return ToolResult("No storage forecast recorded yet.", [], {})
        latest = storage_results[-1]
        outputs = latest.outputs
        content = (
            f"AlphaGasIQ storage forecast: {outputs.get('forecast_bcf'):+.0f} Bcf vs. market consensus "
            f"{outputs.get('market_consensus_bcf')} Bcf for week ending {outputs.get('week_ending')}. "
            f"5-year average: {outputs.get('five_year_average_bcf')} Bcf; last year: {outputs.get('last_year_bcf')} Bcf."
        )
        return ToolResult(content, [c.model_dump(mode="json") for c in latest.citations], {"last_execution_time": latest.last_execution_time.isoformat()})

    def _top_risks(self, state: AppState) -> ToolResult:
        summary = state.portfolio_risk_summary()
        content = (
            f"Gross exposure {summary.gross_exposure}, net exposure {summary.net_exposure}, "
            f"VaR(95) {summary.var_95}, Expected Shortfall(95) {summary.expected_shortfall_95}, "
            f"max drawdown {summary.max_drawdown:.1%}, concentration (HHI) {summary.concentration_hhi}, "
            f"largest single-position share {summary.largest_position_share:.1%}."
        )
        return ToolResult(content, [{"source": "risk_service.metrics", "reference": "portfolio_risk_summary"}], {})

    def _what_changed_overnight(self, state: AppState) -> ToolResult:
        """AlphaSignalTool (docs/alpha-intelligence.md section 43) -- the highest-
        materiality changes AlphaSignal(TM) detected, ranked, not the raw agent
        activity log `_what_changed` below reads."""
        if not state.recent_signals:
            return ToolResult("No material changes detected recently.", [], {})
        top = sorted(state.recent_signals, key=lambda s: s.materiality_score, reverse=True)[:5]
        lines = [
            f"[{s.materiality_score:.0f}] {s.headline} ({s.direction.value}) — {s.description}" for s in top
        ]
        return ToolResult(
            "\n".join(lines),
            [{"source": "alpha_service.signal_detector", "reference": str(s.id)} for s in top],
            {"signal_count": len(state.recent_signals)},
        )

    def _why_does_it_matter(self, state: AppState) -> ToolResult:
        """AlphaImpactTool (docs/alpha-intelligence.md section 43) -- explains the
        highest-materiality recent signal's causal chain, not just that it happened.
        Reads `state.recent_impacts` (populated 1:1 alongside `state.recent_signals`
        by `AppState._run_alpha_signal_detection`), matching by `signal_id` so this
        always reports the impact analysis for the same signal `_what_changed_overnight`
        would surface first."""
        if not state.recent_impacts:
            return ToolResult("No impact analysis available yet -- ask what changed first.", [], {})
        top_signal = max(state.recent_signals, key=lambda s: s.materiality_score, default=None)
        analysis = next(
            (a for a in state.recent_impacts if top_signal is not None and a.signal_id == top_signal.id),
            state.recent_impacts[-1],
        )
        lines = [f"{analysis.event_type.value} -- overall read: {analysis.bullish_bearish.value}"]
        lines += [f"{edge.from_node} -> {edge.to_node}: {edge.description}" for edge in analysis.chain]
        if analysis.uncertainties:
            lines.append("Uncertainties: " + "; ".join(analysis.uncertainties))
        return ToolResult(
            "\n".join(lines),
            [{"source": "alpha_service.impact_engine", "reference": str(analysis.id)}],
            {"signal_id": str(analysis.signal_id)},
        )

    def _agent_consensus_view(self, state: AppState) -> ToolResult:
        """AlphaConsensusTool (docs/alpha-intelligence.md section 43) -- the latest
        dynamically-weighted consensus view, keyed by each contributing agent's
        Agent Alpha Score(TM) rather than a simple majority vote. Reads
        `state.recent_consensus_views`, the same bounded in-memory cache pattern
        `_what_changed_overnight`/`_why_does_it_matter` use for signals/impacts."""
        if not state.recent_consensus_views:
            return ToolResult("No agent consensus view computed yet.", [], {})
        view = state.recent_consensus_views[-1]
        lines = [
            f"{view.consensus_type} consensus for {view.market} ({view.agreement_label} agreement, "
            f"{view.agent_count} agents): bull {view.bull_probability:.0%} / bear {view.bear_probability:.0%} "
            f"/ neutral {view.neutral_probability:.0%}, dispersion {view.dispersion:.2f}."
        ]
        if view.consensus_value is not None:
            lines.append(f"AlphaConsensus value: {view.consensus_value:+.1f}")
            if view.market_consensus_value is not None:
                lines.append(
                    f"Market consensus: {view.market_consensus_value:+.1f} "
                    f"(variance {view.variance_vs_market:+.1f})"
                )
        if view.leading_agents:
            lines.append("Leading agents: " + ", ".join(view.leading_agents))
        if view.dissenting_agents:
            lines.append("Dissenting agents: " + ", ".join(view.dissenting_agents))
        return ToolResult(
            "\n".join(lines),
            [{"source": "alpha_service.consensus_engine", "reference": str(view.id)}],
            {"agent_count": view.agent_count},
        )

    def _what_changed(self, q: str, state: AppState) -> ToolResult:
        hours = 6
        match = re.search(r"(\d+)\s*hour", q)
        if match:
            hours = int(match.group(1))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        recent = [
            r for r in state.agent_execution_log
            if r.last_execution_time.replace(tzinfo=timezone.utc) >= cutoff
        ]
        if not recent:
            return ToolResult(f"No agent activity recorded in the last {hours} hours.", [], {})
        lines = [f"{r.agent_name}: {r.reasoning_summary}" for r in recent[-5:]]
        return ToolResult("\n".join(lines), [{"source": "agent_execution_log", "reference": "recent"}], {"window_hours": hours})

    def _todays_move(self, state: AppState) -> ToolResult:
        if not state.news_events:
            return ToolResult("No news events recorded today.", [], {})
        top = sorted(state.news_events, key=lambda e: e.magnitude, reverse=True)[:3]
        lines = [f"{e.headline} ({e.bullish_bearish}, magnitude {e.magnitude})" for e in top]
        return ToolResult("\n".join(lines), [{"source": e.source, "reference": e.source_url} for e in top], {})

    def _general_status(self, state: AppState) -> ToolResult:
        m1 = state.market_curve[0].value if state.market_curve else None
        content = (
            f"Henry Hub M1 is {m1}. {len(state.trade_ideas)} active trade idea(s). "
            f"Trading halted: {state.trading_halted}. Ask about a specific trade, weather run, "
            "storage forecast, or portfolio risk for more detail."
        )
        return ToolResult(content, [{"source": "market_summary", "reference": "mock_cme"}], {})
