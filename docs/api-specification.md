# API Specification (MVP)

Base URL: `/api/v1`. FastAPI app in `apps/api`. Auth via OAuth2/OIDC-compatible bearer JWT
(`Authorization: Bearer <token>`); every environment ships the local password-grant dev login,
and a real OIDC provider (Authorization Code + PKCE) is available wherever `OIDC_ISSUER_URL` is
configured — see `apps/api/api_app/oidc.py` and the "Auth" section of `docs/architecture.md` §8.
All mutating endpoints require RBAC role checks (`ADMIN`, `TRADER`, `RISK_MANAGER`,
`RESEARCHER`, `VIEWER`), regardless of which login path issued the session JWT.

## Auth

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/login` | dev-mode/bootstrap credential login (`_DEV_USERS`), returns JWT — kept permanently as the platform's break-glass/bootstrap mechanism, not a real-user login path; see `docs/access-model.md` §3 "Bootstrap credentials" |
| POST | `/auth/magic-link/request` | `{email}` — **always** returns the same generic `{"detail": "If an authorized AlphaGasIQ account exists for this email, a secure sign-in link has been sent."}` regardless of whether the email matches a user, its account status, or rate-limiting, to prevent account enumeration. Rate-limited per email and per IP (5 req / 15 min default). An eligible `ACTIVE` user gets a login link; an eligible `INVITED` user gets a fresh invitation link instead |
| GET | `/auth/magic-link/verify?token=...` | Validates a magic-link token (hash lookup, expiry, single-use, revocation, account eligibility), marks it consumed, activates an `INVITED` account, creates a `Session`, and redirects to `/platform#access_token=...` |
| POST | `/auth/logout` | revokes the caller's `Session` row if the token carries one (no-op for a dev-mode/OIDC token) |
| GET | `/auth/sessions` | the caller's own session history |
| GET | `/auth/me` | current user + roles |
| GET | `/auth/me/entitlements` | the caller's effective permission set + feature-entitlement map (Milestone 4's `apps/api/api_app/entitlements.py`), for Milestone 5's frontend to consume |
| GET | `/auth/mode` | `{"oidc_configured": bool}` — whether real SSO is available on this deployment |
| GET | `/auth/oidc/login` | redirects to the configured IdP's authorization endpoint (PKCE); `501` if OIDC isn't configured |
| GET | `/auth/oidc/callback` | IdP redirect target; validates the ID token (JWKS signature, issuer, audience, nonce), maps claims to a `Role` set, and redirects to the frontend (`/platform#access_token=...`) with this platform's own session JWT in the URL fragment |

## Contact (public, no account creation)

| Method | Path | Notes |
|---|---|---|
| POST | `/contact` | Public business-inquiry form submission (first/last name, business email, company, job title, phone, inquiry type, message). Persists a `ContactInquiry` row for admin visibility only. **Never** creates a `User`, `Organization`, `MagicLinkToken`, or session — see `docs/access-model.md` "No Self-Registration." |

## Admin: Users & Organizations (Milestone 2)

Every endpoint below is gated by a real, DB-backed permission check
(`entitlements.require_permission`/`require_any_permission`, Milestone 4) resolved from the
caller's effective permission set — not the placeholder `require_role(Role.ADMIN)` check earlier
milestones used. There is no endpoint anywhere that lets an unauthenticated or non-admin caller
create a `User` or `Organization` — see `docs/access-model.md` "No Self-Registration."

| Method | Path | Notes |
|---|---|---|
| GET | `/admin/roles` | requires `admin.users.view`. The 8 seeded roles (`SUPER_ADMIN`, `ADMIN`, `TRADER`, `RISK_MANAGER`, `RESEARCHER`, `EXECUTIVE`, `VIEWER`, `API_USER`) |
| POST | `/admin/organizations` | requires `admin.organizations`. Create an organization; `409` if the name already exists |
| GET | `/admin/organizations` | requires `admin.organizations`. List organizations |
| POST | `/admin/users` | requires `admin.users.create`. Looks up the organization by `company_name` (creating it inline if it doesn't exist, per spec §14), always creates the user in `INVITED` status regardless of what's requested, `409` on a duplicate (case-insensitive) email, `400` on an unrecognized role |
| GET | `/admin/users` | requires `admin.users.view`. List users, with `organization_name`/`role_name` resolved for display |
| GET | `/admin/users/{user_id}` | requires `admin.users.view`. Single user; `404` if not found |
| POST | `/admin/users/{user_id}/status` | requires `admin.users.suspend` (target `SUSPENDED`/`DISABLED`), `admin.users.revoke` (target `REVOKED`), or `admin.users.edit` (any other target). Transitions a user's account status (`apps/api/api_app/account_states.py`'s state machine); `400` on an illegal transition (e.g. `INVITED`→`ACTIVE`, which only ever happens via magic-link activation, never an admin action). Sends an account-status-change email for `SUSPENDED`/`ACTIVE`/`DISABLED`/`REVOKED` |
| POST | `/admin/users/{user_id}/resend-invitation` | requires `admin.users.edit`. Spec §18 — only valid while `INVITED`; invalidates all prior unused invitation links and sends a fresh one; `400` once the account is no longer `INVITED` |
| GET | `/admin/users/{user_id}/sessions` | requires `admin.users.sessions`. A user's active/past sessions |
| POST | `/admin/users/{user_id}/sessions/{session_id}/revoke` | requires `admin.users.sessions`. Admin-initiated session revocation (spec §20) |
| PATCH | `/admin/users/{user_id}` | requires `admin.users.edit`. Partial profile update — job title/department/phone/country/state_region/primary_use_case/market_experience/expiration_at, plus reassigning `role` (by name) or `company_name` (lookup-or-create) |
| POST | `/admin/users/{user_id}/send-login-link` | requires `admin.users.edit`. Spec §32 "Send login Magic Link" — only valid once the user is `ACTIVE` (distinct from resend-invitation, which is `INVITED`-only) |
| GET | `/admin/users/{user_id}/entitlements` | requires `admin.users.view`. Admin's view of a user's effective permissions/features (spec §32 "View feature usage") |
| PATCH | `/admin/organizations/{organization_id}` | requires `admin.organizations`. Partial update, including `data_entitlements` (spec §32 "Change data entitlements") |
| GET | `/admin/overview` | requires `admin.dashboard`. Executive operating metrics (spec §31) — active/invited/suspended users, active organizations, logins today, Chief Trading Agent query volume, paper-trading activity, and real data-feed health/staleness counts; fields depending on not-yet-built subsystems (model health, risk alerts, failed-auth tracking) report `null` in a `not_yet_available` list |
| GET/PUT | `/admin/features(/{feature_key})` | requires `admin.feature_management`. List/toggle a feature's global `globally_enabled` switch (spec §34) |
| GET/PUT | `/admin/roles/{role_name}/features(/{feature_key})` | requires `admin.feature_management`. View/toggle a role's feature grants |
| PUT | `/admin/organizations/{organization_id}/features/{feature_key}` | requires `admin.feature_management`. Org-level feature override |
| PUT | `/admin/users/{user_id}/features/{feature_key}` | requires `admin.users.features`. Per-user feature override (spec §32's "Enable/disable Chief Trading Agent/Portfolio/Risk Analytics/Paper Trading/API Access") — deny-only for `security_sensitive` features |
| GET/PUT | `/admin/settings(/{key})` | requires `admin.system_settings` (`SUPER_ADMIN`-only). List/get/update a system configuration value (spec §38) |
| GET | `/admin/settings/{key}/history` | requires `admin.system_settings`. Prior versions of one setting |

## Admin: Data Feeds (Milestone 7, spec §§35-37)

| Method | Path | Notes |
|---|---|---|
| GET | `/admin/data-feeds` | requires `admin.data_feeds`. Every registered provider's config merged with its *live* `health_check()` result and its static dependency-map entry — connection status, freshness, priority, affected agents/business functions, dependency chain (spec §35). `data_quality_score` is `null` (honest stub — no scoring model exists yet) |
| GET | `/admin/data-feeds/{provider_id}` | requires `admin.data_feeds`. Single-provider version of the above |
| PATCH | `/admin/data-feeds/{provider_id}` | requires `admin.data_feeds`. Partial update of enabled/paused/polling_frequency_seconds/freshness_threshold_seconds/priority/fallback_provider_id/notes (spec §36). No credential field exists to edit — API keys are environment-provisioned only |
| POST | `/admin/data-feeds/{provider_id}/test-connection` | requires `admin.data_feeds`. Calls the provider's real `health_check()`; records a `data_feed_events` row. A provider exception is caught and recorded as an `error` event, never a 500 |
| POST | `/admin/data-feeds/{provider_id}/refresh` | requires `admin.data_feeds`. Calls the provider's real `fetch()`; records `records_received` and any error the same way |
| GET | `/admin/data-feeds/{provider_id}/events` | requires `admin.data_feeds`. Ingestion log (spec §35 "Errors"/"Records Received"), newest first |
| GET | `/admin/data-feeds/dependency-map` | requires `admin.data_feeds`. The full static provider → agent → business-function dependency map (spec §37), built from `docs/agents.md` §2's real org chart |

## Admin: AI Agent Control Center (Milestone 8, spec §39)

| Method | Path | Notes |
|---|---|---|
| GET | `/admin/agents` | requires `admin.agent_management`. Every `AgentType` seat merged with its catalog entry (team/purpose/business functions/`implemented`/`administrable`), live model/version info where a real instance exists, real execution statistics from `agent_execution_log`, and its admin config (status/thresholds/notes) where one exists |
| GET | `/admin/agents/{agent_type}` | requires `admin.agent_management`. Single-agent version of the above, plus the last 20 raw executions and any recent errors |
| PATCH | `/admin/agents/{agent_type}` | requires `admin.agent_management`. Updates status (`ACTIVE`/`PAUSED`/`DISABLED`/`TESTING`) and confidence/alert/escalation thresholds/notes. 400 for the Risk Governor (visibility only, see `docs/agent-governance.md` §1) or an unimplemented seat; 404 for an unknown `agent_type` |
| POST | `/admin/agents/{agent_type}/run` | requires `admin.agent_management`. Only `CHIEF_TRADING_AGENT` is independently triggerable (409 for every other seat, which executes only as part of its composed research cycle — see `docs/agent-governance.md` §3); refuses with 409 if the Chief Trading Agent's own status is `PAUSED`/`DISABLED` |

## Admin: Agent Versioning + Optimization (Milestone 9, spec §§40-42)

| Method | Path | Notes |
|---|---|---|
| GET | `/admin/agents/{agent_type}/versions` | requires `admin.agent_management`. All versions for one agent, newest first |
| POST | `/admin/agents/{agent_type}/versions` | requires `admin.agent_management`. Creates a new `DRAFT` version — never edits an existing one |
| GET | `/admin/agents/{agent_type}/versions/production` | requires `admin.agent_management`. The agent's current `PRODUCTION` version; 404 if none exists |
| GET | `/admin/agents/{agent_type}/versions/{version_id}` | requires `admin.agent_management`. One version's full config |
| POST | `/admin/agents/{agent_type}/versions/{version_id}/transition` | requires `admin.agent_management`. Moves a version through the fixed `DRAFT → TESTING → APPROVED → PRODUCTION → (RETIRED \| ROLLED_BACK)` lifecycle; 400 on an illegal jump (e.g. straight to `PRODUCTION`). Promoting retires the agent's prior `PRODUCTION` version automatically; approving records `approved_by`/`approved_at` |
| POST | `/admin/agents/{agent_type}/optimization/propose` | requires `admin.agent_optimization` (`SUPER_ADMIN`-only). Records a real performance-review snapshot from `agent_execution_log` plus the admin's stated problem/proposed change, then creates a `DRAFT` version through the same lifecycle above |

## Admin: Model Management, Risk Settings, Audit Log, System Health (Milestone 10, spec §§43-56)

| Method | Path | Notes |
|---|---|---|
| GET | `/admin/models` | requires `admin.model_management` (`SUPER_ADMIN`-only). Every model definition |
| POST | `/admin/models` | requires `admin.model_management`. Creates a new model definition, status `AVAILABLE` |
| GET | `/admin/models/{model_id}` | requires `admin.model_management`. One model's full definition |
| PATCH | `/admin/models/{model_id}/status` | requires `admin.model_management`. Updates status (`AVAILABLE`/`TESTING`/`APPROVED`/`DEPRECATED`/`DISABLED`); audit-logged |
| GET | `/admin/risk-settings` | requires `admin.risk_settings` (`SUPER_ADMIN`-only). Current `RiskLimits` |
| PUT | `/admin/risk-settings` | requires `admin.risk_settings`. Updates the 7 `RiskLimits` fields; requires a non-empty `reason`; records an audit event with before/after |
| GET | `/admin/audit-logs` | requires `admin.audit_logs`. Append-only audit trail, optionally filtered by `?resource_type=`, newest first |
| GET | `/admin/system-health` | requires `admin.dashboard`. Live rollup of data-feed/agent/model health, Risk Governor status, event-bus implementation, and database connectivity |

## System / Observability

| Method | Path | Notes |
|---|---|---|
| GET | `/system/status` | overall system status: services, event bus, DB |
| GET | `/system/freshness` | per-provider freshness + stale flags |
| GET | `/system/providers` | registered providers, classification, health |

## Market Data

| Method | Path | Notes |
|---|---|---|
| GET | `/market/curve/{instrument}` | forward curve M1-M36, with `as_of` compare param |
| GET | `/market/ticks/{symbol}` | recent ticks/settlements |
| GET | `/market/summary` | header strip: HH M1, daily %, M2, 12-mo strip |

## Fundamentals

| Method | Path | Notes |
|---|---|---|
| GET | `/fundamentals/balance/daily` | Lower-48 daily balance series |
| GET | `/fundamentals/storage/forecast` | latest `StorageForecast` |
| GET | `/fundamentals/storage/current` | current inventory, yr-ago, 5yr avg/range, EOS projection |
| GET | `/fundamentals/weather/impact` | latest `WeatherDemandImpact` records |
| GET | `/fundamentals/lng/terminals` | LNG terminal states + netback economics |
| GET | `/fundamentals/power-burn` | power burn estimate by ISO/RTO |
| GET | `/fundamentals/pipeline/graph` | pipeline digital-twin nodes/edges (GeoJSON-friendly) |
| GET | `/fundamentals/pipeline/nodes/{node_id}` | one node + its connected edges (capacity/flow/utilization/maintenance/constraint) |

## News

| Method | Path | Notes |
|---|---|---|
| GET | `/news/events` | structured `NewsEvent` feed, filterable by type/geography |
| GET | `/news/events/{event_id}` | single event with citations |

## Agents

| Method | Path | Notes |
|---|---|---|
| GET | `/agents` | org chart + each agent's current status |
| GET | `/agents/{agent_id}/executions` | recent `AgentResult`s for one agent |
| POST | `/agents/chief-trading/run` | trigger a Chief Trading Agent research cycle (RESEARCHER+) |

## Quantitative

| Method | Path | Notes |
|---|---|---|
| GET | `/quant/forecast` | latest multi-horizon `PriceForecast` from the Forecasting Agent |
| GET | `/quant/regime` | latest `RegimeResult` from the Regime Detection Agent |
| GET | `/quant/relative-value` | latest HH-TTF netback + M1-M2 calendar-spread `RelativeValueSignal`s |
| GET | `/quant/backtest` | latest walk-forward `BacktestResult` per implemented model |
| GET | `/quant/models` | every `ModelType` the platform names, with an honest implemented/not-implemented flag |

## Strategy / Committee

| Method | Path | Notes |
|---|---|---|
| GET | `/trade-ideas` | list `TradeIdea`s, filterable by status/instrument |
| GET | `/trade-ideas/{trade_id}` | single trade idea + explainability payload |
| POST | `/trade-ideas/{trade_id}/challenge` | "Challenge AI" — re-invokes Skeptic + Bear agents |
| POST | `/trade-ideas/{trade_id}/close` | flattens the paper position and generates the post-trade analysis (TRADER/RISK_MANAGER/ADMIN) |
| GET | `/committee-decisions/{trade_id}` | `InvestmentCommitteeDecision` for a trade idea |

## Risk

| Method | Path | Notes |
|---|---|---|
| GET | `/risk/portfolio` | requires the `risk_analytics` feature entitlement (Milestone 5, spec §25/§28). Current exposure/greeks/VaR/ES/drawdown |
| GET | `/risk/limits` | configured limits |
| PUT | `/risk/limits` | update limits (RISK_MANAGER/ADMIN) |
| POST | `/risk/scenarios/{scenario_id}/run` | run a stress scenario |
| GET | `/risk/governor/checks/{trade_id}` | Risk Governor verdict + rule trace for a trade |

## Approvals

| Method | Path | Notes |
|---|---|---|
| GET | `/approvals` | approval workflow items, filterable by state |
| POST | `/approvals/{id}/action` | `{action, payload}` — approve/reject/modify/challenge/etc. (TRADER/RISK_MANAGER/ADMIN) |

## Paper Trading / Portfolio

| Method | Path | Notes |
|---|---|---|
| GET | `/portfolio/positions` | requires the `portfolio_analytics` feature entitlement (Milestone 5). Current paper positions |
| GET | `/portfolio/pnl` | requires `portfolio_analytics`. Daily/realized/unrealized P&L |
| GET | `/portfolio/paper-orders` | requires `portfolio_analytics`. Simulated order/fill history |

## Decision Journal / Post-Trade

| Method | Path | Notes |
|---|---|---|
| GET | `/journal/{trade_id}` | full decision journal entry |
| GET | `/post-trade/{trade_id}` | post-trade analysis once closed |
| GET | `/models/performance` | Milestone 11 model-performance dashboard: win rate, avg thesis/timing/risk accuracy, decision-vs-outcome quadrant counts, and per-strategy breakdown over every closed trade; plus a `quant` section comparing each `services/quant` model's walk-forward-backtested directional accuracy to its live directional accuracy/Brier score from closed trades that had a forecast attached |

## AI Trader Chat

| Method | Path | Notes |
|---|---|---|
| POST | `/chat/sessions` | create a chat session — left open to anonymous exploration (an empty conversation exposes nothing) |
| POST | `/chat/sessions/{id}/messages` | requires the `chief_agent.chat` permission (Milestone 5, spec §26/§28); each topic is further gated per-tool inside `ChatAgent.ask()` by its own required permission (e.g. a portfolio/scenario question needs `portfolio.view`) — an ungranted permission is declined without the tool ever touching real data or an LLM call being made. Send a message; returns assistant reply with citations |
| GET | `/chat/sessions/{id}` | full transcript |
| GET | `/chat/conversations` | requires `admin.audit_logs`. Admin visibility into persisted chat usage metadata (spec §29), optionally filtered by `user_id` |
| GET | `/chat/conversations/{id}/messages` | requires `admin.audit_logs`. Full persisted message history for one conversation |
| WS | `/ws/chat/{id}` | streaming token delivery |

All list endpoints support `limit`/`cursor` pagination. All responses embed
`data_sources`/`citations`/`freshness` metadata wherever the payload includes market or research
facts, per the platform's explainability requirement.

## Alpha Intelligence — AlphaSignal + AlphaImpact + AlphaConsensus + AlphaScenario + AlphaMemory + AlphaReplay + Chief Trading Agent integration (Alpha Intelligence Layer Milestones 1-7, `docs/alpha-intelligence.md`)

| Method | Path | Notes |
|---|---|---|
| GET | `/alpha/signals` | requires `alpha_signals.view`. Ranked highest-materiality-first, then most recent. Query params: `market`, `since_hours` (default 24), `min_materiality` (default 0), `limit` (default 50). Includes both the requester's organization's own signals and every platform-wide signal (`organization_id IS NULL` — the only kind this milestone's detector produces) |
| GET | `/alpha/signals/{signal_id}` | requires `alpha_signals.view`. 404 if unknown |
| GET | `/alpha/impacts` | requires `alpha_impacts.view`. Most-recent-first. Query params: `signal_id`, `since_hours` (default 24), `limit` (default 50). Same organization-scoped-plus-platform-wide visibility rule as `/alpha/signals` |
| GET | `/alpha/impacts/{impact_id}` | requires `alpha_impacts.view`. 404 if unknown |
| GET | `/alpha/consensus` | requires `alpha_consensus.view`. Most-recent-first. Query params: `consensus_type`, `since_hours` (default 24), `limit` (default 50). Same organization-scoped-plus-platform-wide visibility rule as `/alpha/signals` |
| GET | `/alpha/consensus/{market}` | requires `alpha_consensus.view`. Latest `ConsensusView` for the given market (e.g. `HENRY_HUB`) — the flagship "AlphaConsensus vs. Market Consensus" comparison. 404 if none computed yet |
| GET | `/alpha/consensus/by-id/{consensus_id}` | requires `alpha_consensus.view`. 404 if unknown |
| GET | `/alpha/scenarios/library` | requires `alpha_scenarios.view`. The standing stress-test catalog (`risk_service.scenarios.SCENARIOS`) |
| POST | `/alpha/scenarios/run` | requires `alpha_scenarios.run`. Body: `ScenarioDefinition` (`base_scenario_ids`, `variables`). Composes and runs a named and/or custom scenario against the current paper book; 400 on an unknown base scenario id |
| POST | `/alpha/scenarios/compare` | requires `alpha_scenarios.run`. Runs the entire standing library against the current paper book and returns ranked results plus a worst/best-case summary |
| GET | `/alpha/scenarios/runs` | requires `alpha_scenarios.view`. Persisted run history, most-recent-first. Query params: `since_hours` (default 24), `limit` (default 50) |
| GET | `/alpha/scenarios/runs/{run_id}` | requires `alpha_scenarios.view`. 404 if unknown |
| GET | `/alpha/memory` | requires `alpha_memory.view`. Decision memory records, most recent first. Query params: `memory_type`, `since_hours` (default 720 — a 30-day window), `limit` (default 50) |
| GET | `/alpha/memory/{memory_id}` | requires `alpha_memory.view`. 404 if unknown |
| GET | `/alpha/memory/lessons` | requires `alpha_memory.view`. Lesson proposals, most recent first. Query params: `status` (`PENDING`/`APPROVED`/`REJECTED`), `limit` (default 50) |
| GET | `/alpha/memory/lessons/{lesson_id}` | requires `alpha_memory.view`. 404 if unknown |
| POST | `/alpha/memory/lessons/{lesson_id}/review` | requires `alpha_memory.review`. Body: `{"status": "APPROVED"\|"REJECTED"}`; 400 if asked to review back to `PENDING`; 404 if unknown |
| GET | `/alpha/replay` | requires `alpha_replay.view`. Query params: `market` (default `HENRY_HUB`), `as_of` (defaults to now). Returns an `AsOfReplayResult` — every Alpha* series (price observations, signals, impacts, consensus views, scenario runs, decision memory) bitemporally filtered to what was already knowable at `as_of`. `mode` is always `CURRENT_MODEL_RETROSPECTIVE`; an `as_of` before Milestone 6's deployment returns empty lists rather than fabricating history |
| GET | `/alpha/briefs/latest` | requires `alpha_brief.view`. The most recently generated Overnight Intelligence Brief. Query params: `market`. 404 if none generated yet |
| GET | `/alpha/briefs` | requires `alpha_brief.view`. Brief history, most recent first. Query params: `market`, `limit` (default 20) |
| GET | `/alpha/briefs/{brief_id}` | requires `alpha_brief.view`. 404 if unknown |

AlphaSignal, AlphaImpact, AlphaConsensus, AlphaScenario, AlphaMemory, AlphaReplay, and the Chief
Trading Agent integration (AlphaSignal/AlphaConsensus feedback into trade generation, the
Overnight Intelligence Brief) are all implemented now.

## Admin: Enterprise Data Platform foundation (Milestone 8, `docs/alpha-intelligence.md` section 11)

| Method | Path | Notes |
|---|---|---|
| GET | `/admin/workspaces` | requires `admin.workspaces`. Query params: `organization_id` |
| POST | `/admin/workspaces` | requires `admin.workspaces`. Body: `{"organization_id", "name", "description"?}`; 400 if `organization_id` is unknown |
| GET | `/admin/workspaces/{workspace_id}` | requires `admin.workspaces`. 404 if unknown |
| PATCH | `/admin/workspaces/{workspace_id}` | requires `admin.workspaces`. Body: `{"name"?, "description"?}`; 404 if unknown |
| DELETE | `/admin/workspaces/{workspace_id}` | requires `admin.workspaces`. 204; 404 if unknown |
| GET | `/admin/workspaces/{workspace_id}/members` | requires `admin.workspaces`. 404 if the workspace is unknown |
| POST | `/admin/workspaces/{workspace_id}/members` | requires `admin.workspaces`. Body: `{"user_id"}`; adding an existing member is a no-op, not a duplicate |
| DELETE | `/admin/workspaces/{workspace_id}/members/{user_id}` | requires `admin.workspaces`. 204; 404 if not a member |
| GET | `/admin/enterprise-data/sources` | requires `admin.enterprise_data`. Query params: `organization_id`, `workspace_id` |
| POST | `/admin/enterprise-data/sources` | requires `admin.enterprise_data`. Body: `{"organization_id", "workspace_id"?, "name", "connector_type", "classification", "description"?, "connection_config"?}`; 400 if `organization_id` is unknown or `connector_type` isn't a valid `EnterpriseConnectorType`. No credential/secret field exists on this object at all |
| GET | `/admin/enterprise-data/sources/{source_id}` | requires `admin.enterprise_data`. 404 if unknown |
| PATCH | `/admin/enterprise-data/sources/{source_id}` | requires `admin.enterprise_data`. Body: `{"name"?, "status"?, "description"?, "connection_config"?}`; 404 if unknown |
| DELETE | `/admin/enterprise-data/sources/{source_id}` | requires `admin.enterprise_data`. 204; 404 if unknown |
| POST | `/admin/enterprise-data/sources/{source_id}/test-connection` | requires `admin.enterprise_data`. Body: `{"sample_rows"?}` (only meaningful for `MANUAL_UPLOAD`). Runs the source's connector's `test_connection()` and records the result as an event |
| GET | `/admin/enterprise-data/sources/{source_id}/events` | requires `admin.enterprise_data`. Test-connection/ingest event log, most recent first |
| GET | `/admin/enterprise-data/sources/{source_id}/datasets` | requires `admin.enterprise_data`. 404 if the source is unknown |
| POST | `/admin/enterprise-data/sources/{source_id}/datasets` | requires `admin.enterprise_data`. Body: `{"name", "domain", "classification", "sample_rows"?}`. Runs the connector's `discover_schema()` on `sample_rows` to populate `schema_summary`; an unimplemented connector type still creates the dataset, just without a discovered schema |
| GET | `/admin/enterprise-data/datasets/{dataset_id}` | requires `admin.enterprise_data`. 404 if unknown |
| POST | `/admin/enterprise-data/datasets/{dataset_id}/preview` | requires `admin.enterprise_data`. Body: `{"rows"}`. Returns `{"schema", "preview_rows"}`; 400 if the dataset's connector type has no implementation |
| POST | `/admin/enterprise-data/datasets/{dataset_id}/ingest` | requires `admin.enterprise_data`. Body: `{"rows"}`. Persists accepted rows, updates `row_count`/`schema_summary`, records an event; 400 if the connector type has no implementation |
| GET | `/admin/enterprise-data/datasets/{dataset_id}/records` | requires `admin.enterprise_data`. Query params: `limit` (default 50) |
| GET | `/admin/enterprise-data/datasets/{dataset_id}/entitlements` | requires `admin.enterprise_data`. 404 if the dataset is unknown |
| POST | `/admin/enterprise-data/datasets/{dataset_id}/entitlements` | requires `admin.enterprise_data`. Body: `{"principal_type", "principal_id"}` |
| DELETE | `/admin/enterprise-data/datasets/{dataset_id}/entitlements/{entitlement_id}` | requires `admin.enterprise_data`. 204; 404 if unknown |

Milestone 8 is a foundation, honestly: only `MANUAL_UPLOAD` sources have a real connector
implementation (`test-connection`/`preview`/`ingest` on any other `connector_type` return the
connector's own honest `not_configured`/400 response, never a fabricated success). Real
tenant-isolation enforcement, `ModelRoutingPolicy`, and most of the originally-envisioned admin
tabs (Mappings/Lineage/Usage/Dependencies) remain Milestone 9-10 — see
`docs/alpha-intelligence.md` section 11 for the exact built-vs-not-built line.
