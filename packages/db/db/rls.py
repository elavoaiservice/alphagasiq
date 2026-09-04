"""Postgres Row Level Security (docs/alpha-intelligence.md section 11.1): a
database-level backstop for organization-scoped tables, layered on top of --
not instead of -- the application-layer enforcement
`apps/api/api_app/entitlements.resolve_organization_scope`/`record_is_visible`
already provide (Milestone 9).

RLS is a Postgres-specific feature with no SQLite equivalent.
`Repository.apply_row_level_security()` is a documented no-op against the
SQLite database every default `pytest` run and every `uvicorn --reload` dev
session uses (`config.Settings.database_url`'s default) -- application-layer
enforcement remains the *only* backstop there, honestly. A deployment whose
`DATABASE_URL` points at real Postgres (docker-compose, or any managed
Postgres) gets both layers.

Every policy is permissive by default: a row stays visible unless the
caller's session has actually set `app.current_org_id` via
`SELECT set_config('app.current_org_id', <value>, true)` (transaction-scoped
-- `is_local=true` -- so it can never leak across requests or connections
pulled from the pool) -- the same "backward-compatible, opt-in narrowing"
pattern every other entitlement feature in this codebase already follows.
Enabling RLS on a table does not change behavior for any caller that doesn't
(yet) resolve and set its own organization context.

`ORG_SCOPED_TABLES` lists every table with an `organization_id` column --
broad schema-level coverage, matching the "readiness ahead of full plumbing"
posture Milestone 9 already used for the `organization_id` columns it added
to the core trading tables. Only the seven Alpha* `list_*` repository
methods that already resolve `organization_id`/`platform_only` per call
(Milestone 9's cross-organization data-visibility fix) actually set the
session GUC today -- see `Repository._set_org_guc` and its call sites.
Everything else keeps today's unrestricted (GUC-unset) behavior; wiring more
call sites is future work, not something this migration alone provides.
"""

from __future__ import annotations

PLATFORM_ONLY_SENTINEL = "__platform_only__"

ORG_SCOPED_TABLES: tuple[str, ...] = (
    "trade_ideas",
    "committee_decisions",
    "risk_checks",
    "approvals",
    "users",
    "organization_feature_entitlements",
    "chat_conversations",
    "alpha_signals",
    "alpha_impact_analyses",
    "alpha_agent_forecasts",
    "alpha_consensus_views",
    "alpha_scenario_runs",
    "alpha_memory_records",
    "alpha_lesson_proposals",
    "alpha_intelligence_briefs",
    "workspaces",
    "enterprise_data_sources",
    "enterprise_datasets",
    "model_routing_policies",
    "retention_policies",
    "enterprise_opportunities",
)

_ORG_COLUMN = "organization_id"


def build_row_level_security_statements(tables: tuple[str, ...] = ORG_SCOPED_TABLES) -> list[str]:
    """Pure and directly testable: the exact DDL `Repository.
    apply_row_level_security()` executes against a real Postgres connection,
    one statement per call so each can be run independently (some drivers
    reject multiple statements in one `execute()`). `FORCE ROW LEVEL
    SECURITY` is required for the policy to actually apply to the table
    owner -- the role that ran `CREATE TABLE` and every app query in a
    typical deployment -- without it, Postgres exempts the owner from RLS
    entirely and the policy would be silently inert for the app's own
    connection. `DROP POLICY IF EXISTS` first makes this safe to re-run on
    every boot (Postgres has no `CREATE POLICY IF NOT EXISTS`)."""
    statements: list[str] = []
    for table in tables:
        statements.append(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        statements.append(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        statements.append(f'DROP POLICY IF EXISTS org_isolation ON "{table}"')
        statements.append(
            f'CREATE POLICY org_isolation ON "{table}" USING ('
            "current_setting('app.current_org_id', true) IS NULL"
            " OR current_setting('app.current_org_id', true) = ''"
            f" OR (current_setting('app.current_org_id', true) = '{PLATFORM_ONLY_SENTINEL}'"
            f" AND {_ORG_COLUMN} IS NULL)"
            f" OR (current_setting('app.current_org_id', true) NOT IN ('', '{PLATFORM_ONLY_SENTINEL}')"
            f" AND ({_ORG_COLUMN} = current_setting('app.current_org_id', true) OR {_ORG_COLUMN} IS NULL))"
            ")"
        )
    return statements


def resolve_org_guc_value(*, organization_id: str | None, platform_only: bool) -> str:
    """The exact value `Repository._set_org_guc` sets `app.current_org_id`
    to, given the same `organization_id`/`platform_only` precedence every
    Alpha* `list_*` method's own `.where()` filtering already uses:
    `organization_id` (when resolvable) takes precedence over
    `platform_only`, and an empty string means "unrestricted" (matches
    neither branch -- today's default, unchanged behavior)."""
    if organization_id is not None:
        return organization_id
    if platform_only:
        return PLATFORM_ONLY_SENTINEL
    return ""
