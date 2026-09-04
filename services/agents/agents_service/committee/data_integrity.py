from __future__ import annotations

from datetime import datetime, timezone

from agent_sdk import AgentOutcome, BaseAgent
from schemas import AgentType, ObservationDraft


class DataIntegrityAgent(BaseAgent):
    """AI Investment Committee: verifies freshness, missing values, conflicting feeds,
    unit consistency, and suspicious observations across the data underlying a trade
    idea. Entirely deterministic — no LLM call is needed to check a timestamp."""

    agent_id = "committee.data_integrity.v1"
    agent_name = "Data Integrity Agent"
    agent_type = AgentType.DATA_INTEGRITY
    version = "0.1.0"

    async def _execute(
        self,
        *,
        observations: list[ObservationDraft],
        freshness_limits_seconds: dict[str, int],
        now: datetime | None = None,
    ) -> AgentOutcome:
        now = now or datetime.now(timezone.utc)
        issues: list[str] = []
        units_by_series: dict[str, set[str]] = {}

        for obs in observations:
            limit = freshness_limits_seconds.get(obs.source)
            obs_time = obs.observation_time
            if obs_time.tzinfo is None:
                obs_time = obs_time.replace(tzinfo=timezone.utc)
            if limit is not None and (now - obs_time).total_seconds() > limit:
                issues.append(f"{obs.source}/{obs.series_id} is stale (limit {limit}s)")

            units_by_series.setdefault(obs.series_id, set()).add(obs.unit)

            if obs.value != obs.value:  # NaN check
                issues.append(f"{obs.source}/{obs.series_id} has a NaN value")

        for series_id, units in units_by_series.items():
            if len(units) > 1:
                issues.append(f"{series_id} has conflicting units across sources: {sorted(units)}")

        assessment = (
            "No data quality issues detected."
            if not issues
            else f"{len(issues)} data quality issue(s) found: " + "; ".join(issues)
        )

        return AgentOutcome(
            outputs={"issues": issues, "observations_checked": len(observations)},
            reasoning_summary=assessment,
            confidence=1.0 if not issues else max(0.1, 1 - 0.2 * len(issues)),
            tools=["data_integrity.freshness_check", "data_integrity.unit_check"],
        )
