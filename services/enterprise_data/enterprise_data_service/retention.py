"""`RetentionEngine` (docs/alpha-intelligence.md section 11.1, Milestone 9):
resolves how many days a given `EnterpriseDataClassification`'s data may be
retained for an organization, and computes the resulting purge cutoff. A pure
function, zero I/O -- the actual purge (finding matching datasets, deleting
expired `EnterpriseRecordRow`s) is `AppState.apply_retention_policy`'s job,
exactly the same split `ModelRoutingEngine`/`PolicyGatedLLMProvider` use:
policy resolution stays a pure, exhaustively-tested function; the I/O that acts
on the resolved policy lives in `AppState`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from schemas import EnterpriseDataClassification, RetentionPolicy


class RetentionEngine:
    def resolve_retention_days(
        self,
        *,
        data_classification: EnterpriseDataClassification,
        policies: list[RetentionPolicy],
        organization_id: str | None,
    ) -> int | None:
        """`policies` should be every policy visible to `organization_id` (its own
        overrides plus the platform defaults), exactly what
        `Repository.list_retention_policies(organization_id=...)` returns. An
        organization-scoped policy always wins over a platform-default one for the
        same classification. Absent any configured policy for this
        (organization, classification) pair, returns `None` -- no mandatory
        retention, so nothing is purged. This is a deliberately conservative
        default: data is never silently deleted absent an explicit policy."""
        org_policy = next(
            (
                p
                for p in policies
                if p.organization_id == organization_id and p.data_classification == data_classification
            ),
            None,
        )
        if org_policy is not None:
            return org_policy.retention_days

        platform_policy = next(
            (p for p in policies if p.organization_id is None and p.data_classification == data_classification),
            None,
        )
        if platform_policy is not None:
            return platform_policy.retention_days

        return None

    @staticmethod
    def compute_cutoff(retention_days: int | None, *, now: datetime) -> datetime | None:
        if retention_days is None:
            return None
        return now - timedelta(days=retention_days)
