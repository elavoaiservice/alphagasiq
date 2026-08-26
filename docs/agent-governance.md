# Agent Governance — Control Center, Versioning, Optimization & the Risk Governor Boundary

> Status: Milestones 8-10 (§§2-8) are all built, in the same reviewed/tested/committed cadence as
> every other milestone in this codebase. Every agent is still a plain Python class
> (`services/agents`) with a hardcoded `version` string — Milestone 8 adds an admin-only *view and
> operational control* of those classes (enable/disable/pause/resume, thresholds, manual run),
> Milestone 9 adds a real versioning/evaluation/approval data model and workflow around them, and
> Milestone 10 adds model management, admin-governed risk settings, a real append-only audit log,
> and a system health rollup. Nothing yet wires a version's stored config back into how
> `services/agents` actually executes (see §4) — that remains a documented, deliberately-scoped
> limitation, not a hidden gap.

## 1. The one non-negotiable boundary: the Risk Governor

**The Risk Governor is not an agent, is never optimized, and is never reachable from the Agent
Control Center or the agent-optimization workflow described below.**

- `services/risk/risk_service/governor.py`'s `RiskGovernor` is a deterministic, non-LLM rules
  engine today (see `docs/risk-framework.md`). It has no admin- or agent-facing write path now,
  and none will be added by anything in this document.
- No AI agent — and no output of the "Agent Optimization Center" (§5 below) — can disable,
  modify, override, or bypass the Risk Governor, or change its risk limits. Changing risk limits
  is a separate, explicitly-gated admin action (§6, `admin.risk_settings`) with its own audit
  trail — it is never a side effect of an agent version promotion.
- If the Risk Governor is unavailable, the platform fails closed (blocks new risk-taking) — this
  is already true today (`docs/architecture.md` §1) and nothing in the agent-governance design
  weakens it.
- The Agent Control Center (§2) displays the Risk Governor alongside the RISK team's agents for
  visibility (operators need to see its health in one place), but every administrative action
  listed in §3 ("Agent Administration") applies only to LLM-driven agents — the Risk Governor has
  no version, no prompt, and nothing in §3's list applies to it.

## 2. AI Agent Control Center

**Implemented now** (`GET /admin/agents(/{agent_type})`, gated by `admin.agent_management`,
`apps/api/api_app/routers/admin_agents.py`): an admin-only view of every seat in `AgentType`
(`packages/schemas`), grouped by business team exactly as the platform's multi-agent org chart is
already organized (`docs/agents.md`, centralized as the single-source-of-truth catalog in
`apps/api/api_app/agent_catalog.py`):

- **Leadership** — Chief Trading Agent, Chief Investment Agent
- **Fundamental Research** — Supply, Demand, Weather, Storage, Pipeline, LNG, Power
- **Market Intelligence** — Market Data, News Intelligence, Event Detection, Sentiment
- **Quantitative Research** — Forecasting, Regime Detection, Relative Value, Backtesting
- **Strategy** — Directional, Calendar Spread, Basis, Storage Arbitrage, LNG Arbitrage,
  Volatility, Event Strategy
- **Investment Committee** — Bull, Bear, Skeptic, Data Integrity, Portfolio
- **Risk** — Market Risk, Portfolio Risk, Liquidity Risk, Data Risk, Model Risk, **Risk Governor**
  (displayed for visibility only — see §1)

Each entry reports: agent type, team, one-line purpose, business function(s), an honest
`implemented` flag (docs/agents.md §4's roster — not every seat has a real class yet), and (only
for implemented seats) `agent_id`, `version`, `model_provider`/`model` (read from the agent's real
`llm` provider instance — e.g. `AnthropicLLMProvider`/`claude-...` once `ANTHROPIC_API_KEY` is
configured, `MockLLMProvider`/`mock-llm-deterministic` otherwise), execution statistics computed
from real `AgentResult`s in `AppState.agent_execution_log` (total executions, last execution
time/status, average latency, success/error rate), and the admin-editable operational fields
below. The single-agent detail endpoint adds the last 20 raw executions and any recent errors.
Fields the spec calls for that nothing yet computes (confidence history, forecast accuracy,
performance score, token/inference usage, estimated operating cost) are simply not returned —
this platform's honest-stub convention, not a fabricated number.

Agent status values today: `ACTIVE`, `PAUSED`, `DISABLED`, `TESTING` (admin-settable). `DEGRADED`/
`FAILED` are computed states the spec anticipates for a future health-monitoring pass — not yet
derived here, since deriving them honestly needs the health/alerting infrastructure Milestone 10
builds.

## 3. Agent administration

**Implemented now**: authorized administrators (permission: `admin.agent_management`) may
enable/disable/pause/resume an implemented agent and set its confidence/alert/escalation
thresholds and notes (`PATCH /admin/agents/{agent_type}`), and run the Chief Trading Agent
manually (`POST /admin/agents/CHIEF_TRADING_AGENT/run` — the same on-demand research cycle
`POST /agents/chief-trading/run` already exposed, now also reachable through the admin surface
and refusing to run while the agent's own status is `PAUSED`/`DISABLED`).

**Honest limitation, stated plainly rather than hidden:** every other implemented seat (Supply,
Demand, Storage, Weather, Directional Strategy, the five Investment Committee agents, the four
Quantitative Team agents, Pipeline, Chief Investment Agent) is composed *internally* by the Chief
Trading Agent's or Chief Investment Agent's own orchestration code (`services/agents`) — there is
no independent entry point to run one in isolation today, so `POST /admin/agents/{agent_type}/run`
for any of them returns 409 with an explanation rather than faking a run. Likewise, setting a
sub-agent's status to `PAUSED`/`DISABLED` here is recorded and visible in the Control Center, but
does not yet gate that sub-agent's execution inside the composed cycle — wiring per-sub-agent
skip logic into `services/agents`' internal composition is real follow-up work, scoped out of this
milestone the same way every prior milestone in this stream scoped its enforcement to a slice
(e.g. Milestone 5's `require_feature` covering only `portfolio_analytics`/`risk_analytics`) rather
than a full retrofit. The Risk Governor has no admin actions here at all — see §1.

**Direct untested production replacement is never permitted.** Nothing in §2-3 lets an
administrator edit an agent's instructions, model, or configuration in place — that flow (draft ->
test -> evaluate -> approve -> publish -> rollback) is Milestone 9's versioning system (§4 below),
not this one.

## 4. Agent versioning

**Implemented now** (`AgentVersionRow`, `packages/db`; `GET/POST /admin/agents/{agent_type}/
versions`, `GET .../versions/production`, `GET .../versions/{version_id}`, `POST .../versions/
{version_id}/transition`, `apps/api/api_app/routers/admin_agent_versions.py`, gated by
`admin.agent_management`): `id`, `agent_type`, `version`, `model_provider`, `model_name`,
`system_instructions`, `tool_configuration`, `data_sources`, `execution_settings`, `thresholds`,
`created_by`, `created_at`, `status`, `evaluation_results`, `approved_by`, `approved_at`,
`deployment_timestamp`, `notes`.

Status: `DRAFT` → `TESTING` → `APPROVED` → `PRODUCTION` → (`RETIRED` | `ROLLED_BACK`), enforced by
`SqlAppRepository.transition_agent_version_status` against a fixed transition table
(`_AGENT_VERSION_TRANSITIONS`) — an illegal jump (e.g. `DRAFT` straight to `PRODUCTION`) raises
`ValueError`, surfaced as a 400. `TESTING` may also go back to `DRAFT` (send a version back for
rework). Approving a version (`POST .../transition {"status": "APPROVED", "evaluation_results":
{...}}`) records `approved_by`/`approved_at` against the calling administrator — this is the
"explicit approval action recorded against an identified administrator" step 8/9 requires.

**A production agent definition is never overwritten.** Every change — including a prompt edit —
creates a new `AgentVersion` row; nothing ever mutates an existing one. "Promoting a version"
(transitioning to `PRODUCTION`) automatically retires the agent_type's prior `PRODUCTION` row (at
most one exists at a time) and stamps `deployment_timestamp` — it does **not** mean the agent's
Python class is regenerated or replaced; wiring a per-agent runtime read of its `PRODUCTION` row
into `services/agents` (so an agent's actual `_execute()` would use the stored
`system_instructions`/`model_name`) is real follow-up work, honestly not yet done — see the note
in `packages/db/db/models.py`'s `AgentVersionRow` docstring. No prompt change may automatically
bypass evaluation — there is no "publish directly to production" affordance; every promotion must
pass through `TESTING` and `APPROVED` first, and the API enforces this server-side, not just in
a UI's button states.

At boot, every implemented, administrable agent is given a real `PRODUCTION` version snapshotted
from its actual live configuration (`AppState._seed_initial_agent_versions()` — version string
and `model_provider`/`model_name` read straight off the agent's real `llm` provider instance, run
through the same DRAFT→TESTING→APPROVED→PRODUCTION lifecycle rather than inserted directly), so
the versioning system starts populated with the truth rather than empty.

## 5. Agent Optimization Center

**Optimization is controlled, not autonomous. There is no one-click capability that lets an LLM
rewrite and deploy itself**, and nothing in this workflow may modify Risk Governor rules (§1).

Fixed workflow, always in this order:

1. Performance Review
2. Problem Identification
3. Proposed Change
4. New `AgentVersion` Created (status `DRAFT`)
5. Sandbox Test
6. Historical Evaluation
7. Benchmark Comparison
8. Human Review
9. Approval
10. Controlled Deployment
11. Post-Deployment Monitoring
12. Rollback if Needed

**Implemented now**: `POST /admin/agents/{agent_type}/optimization/propose`
(`admin_agent_versions.optimization_router`, gated by `admin.agent_optimization` —
`SUPER_ADMIN`-only, a stricter permission than plain version creation) covers steps 1-4 in one
call — it computes a real performance-review snapshot (total executions, success rate, average
latency) from `AppState.agent_execution_log`, requires the admin to state a problem identification
and proposed change (no automated LLM-generated proposal yet — stated as a scope boundary, not
hidden), and creates a new `DRAFT` `AgentVersion` recording all of it in `notes`. Steps 5-12 (test,
evaluate, compare, review, approve, deploy, monitor, roll back) reuse the exact same
`POST .../versions/{version_id}/transition` endpoint every other version uses — there is no
separate, less-gated path for an optimization-proposed version to reach production faster than a
manually-drafted one.

Steps 1-7 can be assisted by tooling (including an LLM proposing a candidate change), but step 8
("Human Review") is a hard gate — no step past it executes without an explicit approval action
recorded against an identified administrator, and every promotion/rollback is an audit event
(§7). Supported optimization-input metrics: forecast accuracy, directional accuracy, calibration,
Brier score, latency, data quality, agent agreement/disagreement, false positive/negative rate,
trade-recommendation contribution, portfolio contribution, human acceptance/rejection rate,
post-trade accuracy, citation quality, tool utilization, error rate, cost per execution.
Comparison views let an administrator line up the current production version, a candidate,
the previous version, and a benchmark model across accuracy, risk-adjusted contribution,
confidence calibration, latency, data coverage, error rate, cost, and historical performance.

## 6. Model management & risk settings

**Implemented now**: `ModelDefinitionRow` (`packages/db`) tracks provider, model name/version,
purpose, status, context window, and per-1k-token input/output cost behind
`GET/POST /admin/models`, `GET /admin/models/{model_id}`, and
`PATCH /admin/models/{model_id}/status` (`apps/api/api_app/routers/admin_models.py`, gated by
`admin.model_management` — `SUPER_ADMIN`-only). Status: `AVAILABLE` → `TESTING` → `APPROVED` →
(`DEPRECATED` | `DISABLED`). **An agent may never be configured to use a model that isn't
`APPROVED`** — enforced structurally, not just by admin-UI convention:
`SqlAppRepository.transition_agent_version_status` (Milestone 9) refuses to move an
`AgentVersion` whose `model_name` doesn't match an `APPROVED` `ModelDefinitionRow` into `APPROVED`
or `PRODUCTION`, raising `ValueError` (surfaced as 400) otherwise. At boot, the one LLM model
every agent is actually configured with (`AppState.llm.model` — `mock-llm-deterministic` in dev,
the real Anthropic model once `ANTHROPIC_API_KEY` is configured) is seeded as `APPROVED`, so the
platform's real agents always have a real, approved model definition to point at.

Risk settings (maximum position size, risk per trade, daily loss, drawdown, portfolio VaR,
contract exposure, correlated exposure) are editable via `GET/PUT /admin/risk-settings`
(`apps/api/api_app/routers/admin_governance.py`, gated by `admin.risk_settings` — `SUPER_ADMIN`-
only). Every write requires a non-empty `reason`, records an audit event with the previous and
new value together, and stamps a fresh `effective_from` timestamp — spec §44's "authorized role,
confirmation, a reason, an effective timestamp, an audit event, and the previous and new value
recorded together." This sits alongside (not instead of) the pre-existing `PUT /risk/limits` a
`RISK_MANAGER` already uses for day-to-day limit changes; both write the same underlying
`RiskLimits`/`RiskLimitsRow`, but only this admin surface is `SUPER_ADMIN`-gated, reason-required,
and audit-logged. **Scope boundary, stated plainly:** the stale-market-data threshold,
abnormal-volatility threshold, and minimum-strategy-confidence fields spec §44 also lists are
covered by System Settings' existing generic `alert_thresholds`/`data_freshness_policies` keys
(Milestone 6) rather than new dedicated columns here — not fabricated as separate fields that
don't yet do anything.

## 7. Audit logging

**Implemented now**: `AuditEventRow` (`packages/db`) is a genuinely append-only table — `id`,
`actor_user_id`, `action`, `resource_type`, `resource_id`, `before`, `after`, `reason`,
`occurred_at` — written only by `SqlAppRepository.record_audit_event`; **there is no
corresponding update or delete method, in the repository or the API, ever.**
`GET /admin/audit-logs` (optionally filtered by `resource_type`, gated by `admin.audit_logs`)
reads it back. Wired into every sensitive action this document names that already exists as an
API endpoint: agent status change (`PATCH /admin/agents/{agent_type}`, Milestone 8), agent version
promotion/rollback (`POST .../versions/{version_id}/transition` reaching `PRODUCTION` or
`ROLLED_BACK`, Milestone 9), model status change (`PATCH /admin/models/{model_id}/status`, §6
above), risk-setting change (§6 above), and admin user status change
(`POST /admin/users/{user_id}/status`, Milestone 2). **Scope boundary, stated plainly:** not every
admin mutation in this codebase writes an audit event yet — organization edits and the
Milestone 6 feature/system-setting toggles are not retrofitted here (`system_settings` already
carries its own dedicated versioned history table since Milestone 6, which substantially serves
the same purpose for that specific surface). Extending audit coverage to the remaining admin
mutations is straightforward follow-up work using the exact same `record_audit_event` helper
(`apps/api/api_app/audit.py`), not a new mechanism to build. See `docs/access-model.md` §1 for the
account-model side of the same audit requirement.

## 8. System architecture & health view

**Implemented now**: `GET /admin/system-health` (gated by `admin.dashboard`,
`apps/api/api_app/routers/admin_governance.py`) rolls up live health at each stage from data
already tracked elsewhere in this platform — data-feed health/count (Milestone 7's live
`health_check()` snapshots), agent status breakdown (Milestone 8's `AgentConfigRow`s), model
approval counts (§6 above), the Risk Governor's operational status and version, the configured
event-bus implementation, and database connectivity — nothing fabricated. A full graphical
pipeline visualization (external data sources → data & intelligence fabric → agent teams →
business functions → Investment Committee → Risk Governor → human oversight → paper
execution/portfolio → decision journal, rendered visually with the agent-to-business-function
mapping from §2) is frontend work building on this endpoint's data, not yet built — this endpoint
is the real, honest data source such a view would consume.
