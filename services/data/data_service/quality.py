"""Phase 1 free-data-feed integration (docs/data-sources.md): deterministic data
quality scoring. A 0-100 score attached to `ObservationDraft.quality_score` --
computed here, never delegated to an LLM, so quantitative data quality is
reproducible and auditable. Checks are simple, documented Phase-1 heuristics (missing/
impossible values, timestamp sanity, a jump check against the prior observation for
the same series), not a statistical anomaly-detection model.
"""

from __future__ import annotations

from datetime import datetime, timezone

from schemas import ObservationDraft

# Categories where a negative value is physically impossible. Not exhaustive --
# categories absent from this map are not value-range-checked at all (honest scope,
# not a claim of universal validation).
_MIN_VALUE_BY_CATEGORY: dict[str, float] = {
    "STORAGE": 0.0,
    "PRODUCTION": 0.0,
    "CONSUMPTION": 0.0,
    "LNG": 0.0,
    "POWER_BURN": 0.0,
}
_TEMPERATURE_BOUNDS_DEGF = (-100.0, 150.0)
_MAX_JUMP_RATIO = 5.0  # a >5x change between consecutive readings is flagged, not blocked


class DataQualityService:
    """`score()` never raises and never returns a value outside [0, 100] -- a
    provider's `fetch()` (or a caller batch-scoring a fetched list) can always attach
    the result to `ObservationDraft.quality_score` unconditionally."""

    def score(
        self,
        draft: ObservationDraft,
        *,
        prior: ObservationDraft | None = None,
        now: datetime | None = None,
    ) -> float:
        now = now or datetime.now(timezone.utc)
        points = 100.0

        if draft.value is None:
            return 0.0

        min_value = _MIN_VALUE_BY_CATEGORY.get(draft.category)
        if min_value is not None and draft.value < min_value:
            points -= 60.0

        if draft.category == "WEATHER" and draft.unit == "DEGF":
            low, high = _TEMPERATURE_BOUNDS_DEGF
            if not (low <= draft.value <= high):
                points -= 60.0

        obs_time = draft.observation_time
        if obs_time.tzinfo is None:
            obs_time = obs_time.replace(tzinfo=timezone.utc)
        if obs_time > now:
            points -= 40.0  # a future-dated observation is never valid

        if prior is not None and prior.value not in (None, 0) and prior.series_id == draft.series_id:
            change_ratio = abs(draft.value - prior.value) / abs(prior.value)
            if change_ratio > _MAX_JUMP_RATIO:
                points -= 30.0

        return max(0.0, min(100.0, points))

    def score_batch(self, drafts: list[ObservationDraft], *, now: datetime | None = None) -> list[float]:
        """Scores a batch of drafts from one `fetch()` call, using each series'
        immediately-preceding draft in the same batch (sorted by `observation_time`)
        as `prior` for the jump check -- the closest approximation to "the last known
        value" available without an extra DB round trip per draft."""
        by_series: dict[str, list[ObservationDraft]] = {}
        for draft in drafts:
            by_series.setdefault(draft.series_id, []).append(draft)
        prior_by_id: dict[int, ObservationDraft | None] = {}
        for series_drafts in by_series.values():
            ordered = sorted(series_drafts, key=lambda d: d.observation_time)
            for i, draft in enumerate(ordered):
                prior_by_id[id(draft)] = ordered[i - 1] if i > 0 else None
        return [self.score(draft, prior=prior_by_id.get(id(draft)), now=now) for draft in drafts]
