# Database Schema

Postgres 16 + TimescaleDB. `infrastructure/db/migrations` defines the canonical
production DDL. The trading-object subset of this schema (trade ideas, committee
decisions, risk checks, approvals, decision journal, post-trade analyses, risk limits —
the tables `apps/api/api_app/state.py` mutates on every trade lifecycle event) is also
mirrored as async SQLAlchemy 2.0 models in `packages/db/db/models.py`, backing the real
`SqlAppRepository` (`packages/db/db/repository.py`) that persists `AppState` — see
"Persistence" in `docs/architecture.md` §8. Everything else in this document (the
`observations` hypertable, pipeline graph, LNG/power-burn/storage reference tables) is
the full production schema the migrations create; only the tables above currently have
a live SQLAlchemy-backed read/write path.

## 1. Canonical Time-Series Observation

Every numeric fact used anywhere in a trading decision is stored as one row in
`observations` (a TimescaleDB hypertable partitioned on `observation_time`). This is the single
most important table in the system: it is what lets the platform answer "what did we know, and
when did we know it."

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `source` | text | e.g. `EIA`, `NOAA_NWS`, `MOCK_CME`, `USER` |
| `source_type` | enum | `PUBLIC` / `LICENSED` / `USER_PROVIDED` / `SIMULATED` |
| `series_id` | text | provider-native series identifier |
| `symbol` | text, nullable | normalized instrument symbol, if applicable |
| `commodity` | text | `NATURAL_GAS`, `POWER`, `LNG`, ... |
| `category` | text | `PRICE`, `STORAGE`, `WEATHER`, `PRODUCTION`, `PIPELINE_FLOW`, `NEWS_EVENT`, ... |
| `sub_category` | text, nullable | e.g. `HDD`, `FEEDGAS`, `DRY_GAS_PRODUCTION` |
| `geography` | text, nullable | `LOWER_48`, `US`, region code |
| `location` | text, nullable | hub, basin, terminal, node id |
| `value` | numeric | |
| `unit` | text | `BCF`, `BCF_D`, `USD_MMBTU`, `DEGREE_DAY`, ... |
| `observation_time` | timestamptz | when the fact is *true of the world* |
| `publication_time` | timestamptz | when the source *published* it — used for backtest/point-in-time correctness |
| `received_time` | timestamptz | when AlphaGasIQ ingested it |
| `revision_number` | int | source revisions (e.g. EIA weekly revisions) increment this |
| `quality_score` | numeric, nullable | 0-1 data-quality confidence from Data Integrity checks |
| `confidence` | numeric, nullable | source/model confidence, distinct from quality |
| `metadata` | jsonb | provider-specific extra fields |
| `lineage` | jsonb | upstream ids/urls this observation derives from |
| `created_at` | timestamptz | row insert time |

Indexes: `(series_id, observation_time)`, `(commodity, category, observation_time)`,
`(source, publication_time)`. TimescaleDB compression policy on chunks older than 90 days.

**Point-in-time rule:** any model/backtest query MUST filter on `publication_time <= as_of`,
never `observation_time <= as_of` alone — this is what prevents look-ahead bias (see
`services/quant/app/pit.py`).

## 2. Agent Execution Records

`agent_executions` — one row per agent run, mirroring the mandatory `AgentResult` contract
(`docs/agents.md`):

`id, agent_id, agent_name, agent_type, version, status, inputs (jsonb), outputs (jsonb),
tools (jsonb), data_sources (jsonb), confidence, started_at, last_execution_time,
execution_duration_ms, reasoning_summary (text), citations (jsonb), errors (jsonb), created_at`

No column for chain-of-thought. `reasoning_summary` is a concise, human-auditable rationale only.

## 3. Trading Objects

- **`trade_ideas`** — mirrors `TradeIdea` (trade_id, strategy, instrument, instrument_type,
  direction, entry, target, stop_or_invalidation, time_horizon, expected_return, expected_loss,
  probability_success, confidence, thesis, catalysts (jsonb), risks (jsonb),
  invalidation_conditions (jsonb), supporting_data (jsonb), source_citations (jsonb),
  created_at, expires_at).
- **`committee_decisions`** — mirrors `InvestmentCommitteeDecision`, FK to `trade_ideas`
  (original_trade_id), plus bull_case/bear_case/skeptic_case/data_quality_assessment/
  portfolio_effect (all text/jsonb), consensus_score, unresolved_questions (jsonb),
  recommended_action enum (`APPROVE_FOR_REVIEW`/`REJECT`/`WAIT_FOR_MORE_DATA`/`REDUCE_SIZE`).
- **`risk_checks`** — one row per Risk Governor evaluation: trade_idea_id, rule_results (jsonb),
  verdict enum (`ALLOW`/`BLOCK`/`REQUIRE_HUMAN`/`HALT`/`REJECT`), evaluated_at, governor_version.
- **`approvals`** — human approval workflow state machine instances: id, trade_idea_id, state
  enum (`DRAFT`/`AI_REVIEW`/`RISK_REVIEW`/`HUMAN_REVIEW`/`APPROVED_FOR_PAPER_TRADING`/
  `REJECTED`/`EXPIRED`/`EXECUTED_SIMULATION`/`CLOSED`), actions (jsonb array, append-only log of
  approve/reject/modify/challenge/request_more_analysis/reduce_position/change_invalidation),
  current_user_id, updated_at.
- **`paper_orders`** / **`paper_fills`** / **`paper_positions`** — simulated execution + book.
- **`decision_journal`** — append-only: id, trade_idea_id, data_snapshot_ids (jsonb), market_state
  (jsonb), news_state (jsonb), weather_state (jsonb), model_versions (jsonb), agent_versions
  (jsonb), thesis (text), counter_thesis (text), risk_analysis (jsonb), human_decision (jsonb),
  paper_execution (jsonb), outcome (jsonb, filled on close), created_at. Rows are never updated;
  corrections are new rows referencing `supersedes_id`.
- **`post_trade_analyses`** — expected vs actual outcome, forecast_error, thesis_accuracy,
  timing_accuracy, risk_accuracy, model_contribution (jsonb), unexpected_events (jsonb), lessons
  (text), quadrant enum (`GOOD_DECISION_GOOD_OUTCOME`, `GOOD_DECISION_BAD_OUTCOME`,
  `BAD_DECISION_GOOD_OUTCOME`, `BAD_DECISION_BAD_OUTCOME`). Also carries `quant_model_type`,
  `quant_model_version`, `quant_predicted_return`, `quant_forecast_error`, and
  `quant_up_probability` — populated only when a `services/quant` `PriceForecast` was attached to
  the trade at creation time, scoring the *model's* prediction separately from the strategy's own
  thesis (see `services/paper-execution/paper_execution_service/post_trade.py`). This is what lets
  `GET /models/performance` compare a model's walk-forward-backtested skill to its live skill on
  the same metrics.

## 4. Domain Reference Tables

- **`news_events`** — mirrors the structured news event object (event_id, headline, source,
  source_url, published_at, detected_at, event_type, entities (jsonb), locations (jsonb),
  summary, supply_impact_bcf_day, demand_impact_bcf_day, expected_duration, affected_markets
  (jsonb), bullish_bearish, magnitude, confidence, citations (jsonb)).
- **`weather_demand_impacts`** — model, run, comparison_run, hdd_delta, cdd_delta,
  estimated_rescom_delta_bcf, estimated_power_burn_delta_bcf, total_demand_delta_bcf,
  price_direction, confidence, created_at.
- **`storage_forecasts`** — week_ending, forecast_bcf, market_consensus_bcf,
  five_year_average_bcf, last_year_bcf, forecast_range_low, forecast_range_high, confidence,
  drivers (jsonb), regional_breakdown (jsonb), created_at.
- **`gas_balance_daily`** — flow_date, production_bcf, canadian_imports_bcf, lng_sendout_bcf,
  other_supply_bcf, rescom_demand_bcf, industrial_demand_bcf, power_burn_bcf,
  lng_feedgas_bcf, mexico_exports_bcf, other_exports_bcf, supply_total_bcf, demand_total_bcf,
  balance_bcf, implied_storage_flow_bcf, created_at.
- **`pipeline_nodes`** / **`pipeline_edges`** — the graph-based digital twin (see
  `docs/architecture.md` §6, node types: production_basin, processing_plant,
  pipeline_interconnect, storage_facility, city_gate, power_plant, LNG_terminal, export_point,
  hub; edge types: pipeline, transport_contract, interconnect; edges carry capacity,
  scheduled_flow, actual_flow, utilization, direction, maintenance, constraint, tariff,
  basis_relationship as jsonb/typed columns). This migration's relational shape mirrors the
  in-memory `PipelineGraph` `services/fundamentals/fundamentals_service/pipeline_graph.py`
  builds at boot; a real Neo4j-backed alternative now also exists
  (`pipeline_graph_neo4j.py`, `NEO4J_URI` config-gated, off by default) — see
  `docs/architecture.md` §8 "Neo4j-backed pipeline graph".
- **`lng_terminals`** — name, location (geography point), capacity_bcf_d, feedgas_bcf_d,
  utilization, maintenance_status, outage_status, estimated_cargo_loadings (jsonb).
- **`market_ticks`** / **`forward_curve_points`** — normalized market data, continuous contract
  id preserved alongside literal contract identifiers.
- **`positions`** — live paper portfolio state: instrument, quantity, avg_price, delta, gamma,
  vega, realized_pnl, unrealized_pnl.
- **`risk_limits`** — configurable: max_position_size, max_risk_per_trade, max_daily_loss,
  max_drawdown, max_portfolio_var, max_sector_exposure, max_contract_exposure,
  max_correlated_exposure, effective_from, effective_to, set_by_user_id.
- **`users`** / **`roles`** / **`permissions`** / **`role_permissions`** / **`organizations`** —
  the real, admin-provisioned account model (`packages/db/db/models.py`:
  `UserRow`/`RoleRow`/`PermissionRow`/`RolePermissionRow`/`OrganizationRow`), replacing the
  placeholder 5-role list above. See `docs/access-model.md` for the full account lifecycle,
  RBAC seed data, and why `apps/api/api_app/auth.py`'s dev-mode `Role` enum (`ADMIN`, `TRADER`,
  `RISK_MANAGER`, `RESEARCHER`, `VIEWER`) still gates every router today — it is the interim
  enforcement mechanism until Milestone 4 wires `require_permission(...)` against these tables.
  `organizations.name` is unique and looked-up-or-created-inline when an admin creates a user
  (spec §14); `users.email` is unique and always stored lowercase.
- **`audit_log`** — append-only record of every mutating action (who, what, when, before/after).
  Not yet implemented as a real table (lands in Milestone 10 as `AuditEvent` — see
  `docs/access-model.md` §7); this row remains a forward-looking placeholder until then.

## 4a. Account & RBAC Tables (Milestone 2)

- **`organizations`** — id, name (unique), website, industry, company_type, country,
  state_region, status, billing_plan, account_owner, primary_contact, feature_package,
  data_entitlements (jsonb), notes, created_at, updated_at.
- **`users`** — id, first_name, last_name, email (unique, lowercase), organization_id (FK),
  job_title, department, phone, country, state_region, primary_use_case, market_experience,
  role_id (FK), status, expiration_at, created_by, created_at, updated_at, activated_at,
  last_login_at. `status` is one of `INVITED`/`ACTIVE`/`SUSPENDED`/`DISABLED`/`EXPIRED`/
  `LOCKED`/`REVOKED` (`apps/api/api_app/account_states.py` enforces the legal transitions
  between them — see `docs/access-model.md` §2). Only ever created by
  `POST /admin/users` — no other writer exists.
- **`roles`** — id, name (unique), description. Seeded with the 8 fixed roles
  (`SUPER_ADMIN`, `ADMIN`, `TRADER`, `RISK_MANAGER`, `RESEARCHER`, `EXECUTIVE`, `VIEWER`,
  `API_USER`) by `SqlAppRepository.seed_rbac_defaults()` on every boot (idempotent).
- **`permissions`** — id, key (unique), description. Seeded with the full permission-key list
  from `docs/access-model.md` §5.
- **`role_permissions`** — id, role_id (FK), permission_id (FK). Each seeded role's default
  grants, now read by every `/admin/*` endpoint's `require_permission(...)` check (Milestone 4).
- **`features`** / **`role_feature_entitlements`** / **`organization_feature_entitlements`** /
  **`user_feature_overrides`** (Milestone 4) — the feature-entitlement model from spec §24.
  `features`: id, key (unique), name, description, security_sensitive, globally_enabled.
  `role_feature_entitlements`: id, role_id (FK), feature_id (FK), enabled (deny-by-default: a
  role only has a feature via an explicit `enabled=True` row). `organization_feature_entitlements`:
  id, organization_id (FK), feature_id (FK), enabled (allow-by-default: only an explicit
  `enabled=False` row restricts). `user_feature_overrides`: id, user_id (FK), feature_id (FK),
  enabled (deny-only for `security_sensitive` features, full override otherwise — see
  `apps/api/api_app/entitlements.py`).
- **`magic_link_tokens`** (Milestone 3) — id, user_id (FK), token_hash (unique, sha256 — the raw
  token is never stored), purpose (`INITIAL_INVITATION`/`LOGIN`/`ACCOUNT_RECOVERY`), created_at,
  expires_at, consumed_at, revoked_at, requested_ip, user_agent.
- **`sessions`** (Milestone 3) — id, user_id (FK), created_at, expires_at, revoked_at,
  ip_address, user_agent, last_seen_at. Only magic-link-issued JWTs carry a `sid` claim pointing
  at one of these rows (`apps/api/api_app/auth.py`) — dev-mode/OIDC sessions remain stateless and
  have no row here.
- **`system_settings`** / **`system_setting_history`** (Milestone 6, spec §38) — admin-editable
  non-sensitive platform configuration. `system_settings`: key (primary key), value (jsonb),
  version, updated_by, updated_at. `system_setting_history`: id, key, value (jsonb), version,
  changed_by, changed_at — every write to `system_settings` appends the row's *previous* state
  here first, giving the "versioned, timestamped, reversible" guarantee spec §38 asks for.
- **`chat_conversations`** / **`chat_messages`** (Milestone 5, spec §29) — persisted Chief
  Trading Agent Chat history behind the existing in-memory `ChatSession`/`ChatMessage` response
  contract (`chat_conversations.id` is the same UUID the API already returns as a session id).
  `chat_conversations`: id, user_id, organization_id (FK, nullable), created_at.
  `chat_messages`: id, conversation_id (FK), role, content, citations (jsonb), freshness (jsonb),
  tool_used, model, latency_ms, permissions_context (jsonb — roles + which permission was checked
  + whether it was granted), created_at. No column exists for a chain-of-thought — there isn't
  one to persist, since the tool layer returns retrieved facts, not a reasoning transcript.
- **`data_feed_configs`** / **`data_feed_events`** (Milestone 7, spec §§35-37) — admin-visible
  data-feed configuration and ingestion log. `data_feed_configs`: provider_id (primary key,
  matches `BaseDataProvider.provider_id`), enabled, paused, polling_frequency_seconds,
  freshness_threshold_seconds, priority, fallback_provider_id, notes, updated_by, updated_at.
  **Deliberately has no credential/secret column** — every provider's API key is
  environment-provisioned via `packages/config/config/settings.py` and never enters the database,
  which is the strongest possible reading of "credentials must never be redisplayed after entry."
  One row is seeded per currently-registered provider at boot, idempotently (existing rows /
  admin edits are never overwritten). `data_feed_events`: id, provider_id, event_type
  (`test_connection`/`manual_refresh`), status (`success`/`error`), detail, records_received,
  latency_ms, occurred_at — an append-only ingestion log, one row per admin-triggered
  test-connection or manual-refresh action.
- **`agent_configs`** (Milestone 8, spec §39) — admin-editable operational state for one
  implemented agent seat. agent_type (primary key, an `AgentType` value), status
  (`ACTIVE`/`PAUSED`/`DISABLED`/`TESTING`), confidence_threshold, alert_threshold,
  escalation_threshold, notes, updated_by, updated_at. Seeded one row per currently-implemented,
  administrable agent type at boot (idempotent — admin edits are never overwritten); the Risk
  Governor deliberately has no row here (see `docs/agent-governance.md` §1).
- **`agent_versions`** (Milestone 9, spec §§40-41) — one row per agent configuration version, never
  mutated after creation. id, agent_type, version, model_provider, model_name, system_instructions,
  tool_configuration (jsonb), data_sources (jsonb), execution_settings (jsonb), thresholds (jsonb),
  status (`DRAFT`/`TESTING`/`APPROVED`/`PRODUCTION`/`RETIRED`/`ROLLED_BACK`), created_by, created_at,
  evaluation_results (jsonb, nullable), approved_by, approved_at, deployment_timestamp, notes.
  `SqlAppRepository.transition_agent_version_status` enforces the fixed lifecycle against a
  transition table — no status jump may skip a step. Promoting a version to `PRODUCTION`
  automatically retires the agent_type's prior `PRODUCTION` row, so at most one exists at a time.
  Every implemented, administrable agent gets a real `PRODUCTION` row seeded from its actual live
  configuration at boot (`AppState._seed_initial_agent_versions()`).
- **`model_definitions`** (Milestone 10, spec §43) — one row per LLM model available for agent
  assignment. id, provider, model_name, version, purpose, approved_agent_types (jsonb), status
  (`AVAILABLE`/`TESTING`/`APPROVED`/`DEPRECATED`/`DISABLED`), context_window,
  cost_per_1k_input_tokens, cost_per_1k_output_tokens, notes, created_at, updated_by, updated_at,
  approved_at. `SqlAppRepository.transition_agent_version_status` (Milestone 9) consults this table:
  an `AgentVersion` may only reach `APPROVED`/`PRODUCTION` with a `model_name` matching an
  `APPROVED` row here. The one LLM model every agent is actually configured with is seeded
  `APPROVED` at boot (`AppState.seed()`), so this constraint is satisfiable from a fresh install.
- **`audit_events`** (Milestone 10, spec §55) — a genuinely append-only log. id, actor_user_id,
  action, resource_type, resource_id, before (jsonb, nullable), after (jsonb, nullable), reason
  (nullable), occurred_at. `SqlAppRepository` exposes only `record_audit_event`/
  `list_audit_events` — there is no update or delete method for this table, in the repository or
  the API, ever.

## 4b. Alpha Intelligence Tables (Alpha Intelligence Layer Milestones 1-5 — `docs/alpha-intelligence.md`)

- **`alpha_signals`** — one row per `Signal` AlphaSignal(TM) detected and persisted. id,
  organization_id (nullable FK to `organizations`, NULL = platform-wide — the only kind
  Milestone 1 produces), workspace_id (nullable, reserved for a future Workspace entity),
  signal_type, category, subcategory, source_ids (jsonb), detected_at, effective_at (nullable),
  market, geography (nullable), asset_ids (jsonb), headline, description, previous_value,
  current_value, absolute_change, percent_change, z_score, historical_percentile,
  materiality_score, novelty_score, confidence, direction, time_horizon, data_quality,
  citations (jsonb), affected_agents (jsonb), affected_business_functions (jsonb), status,
  created_at.
- **`alpha_signal_baselines`** — the last-known value + bounded rolling window per detector
  metric key (e.g. `"STORAGE.forecast_bcf"`), natural-key PK `key`, so
  `alpha_service.signal_detector.SignalDetector` can diff cycle-over-cycle without holding
  that state in the process-wide `AppState` singleton itself: key, value, rolling_window
  (jsonb), observed_at.
- **`alpha_impact_analyses`** — one row per `ImpactAnalysis` AlphaImpact(TM) produced for a
  `Signal` (`signal_id`, FK to `alpha_signals`). id, signal_id, organization_id (nullable FK
  to `organizations`), event_type, physical_impact, supply_impact_bcf_day,
  demand_impact_bcf_day, storage_impact_bcf, expected_duration, affected_geographies (jsonb),
  affected_assets (jsonb), affected_markets (jsonb), affected_contracts (jsonb, always empty
  until the Enterprise Data Platform milestones), basis_implications, curve_implications,
  volatility_implications, portfolio_implications, risk_implications, bullish_bearish,
  magnitude, confidence, assumptions (jsonb), uncertainties (jsonb),
  alternative_interpretations (jsonb), data_sources (jsonb), agent_contributors (jsonb),
  `chain` (jsonb — the ordered `ImpactEdge` list, embedded rather than a separate join table
  since it's always fetched with its parent and never queried edge-by-edge independently),
  created_at.
- **`alpha_agent_forecasts`** — one row per `AgentForecast` extracted from a contributing
  agent's research-cycle output by `alpha_service.forecast_extractor.ForecastExtractor`. id,
  agent_id, agent_type, agent_version, organization_id (nullable FK to `organizations`),
  forecast_type, target, market (default `HENRY_HUB`), horizon, forecast_value (nullable),
  direction, probability, confidence, drivers (jsonb), citations (jsonb), created_at,
  expires_at (nullable).
- **`alpha_agent_scores`** — Agent Alpha Score(TM)'s latest score per agent type. Natural-key
  PK `agent_type` (upserted every cycle, not a history table — a score trend over time is
  explicitly deferred future work): agent_type, score (0-100), method (`BACKTESTED_
  DIRECTIONAL_ACCURACY` or `CONFIDENCE_CONSISTENCY_PROXY`), sample_size, components (jsonb),
  computed_at.
- **`alpha_consensus_views`** — one row per `ConsensusView` AlphaConsensus(TM) computed. id,
  organization_id (nullable FK to `organizations`), consensus_type (e.g. `MARKET_DIRECTION` or
  the specialized `STORAGE_FORECAST`), market (default `HENRY_HUB`), target, horizon,
  consensus_value (nullable — only set when every contributing forecast shares the same
  target), bull_probability, bear_probability, neutral_probability, confidence, dispersion,
  agreement_label (HIGH/MEDIUM/LOW), agent_count, `agent_weights` (jsonb — the embedded
  `ConsensusWeight` list, for the same reason `ImpactAnalysisRow.chain` is embedded), 
  leading_agents (jsonb), dissenting_agents (jsonb), drivers (jsonb), risks (jsonb),
  market_consensus_value (nullable), variance_vs_market (nullable), created_at.
- **`alpha_scenario_runs`** — one row per `ScenarioRunResult` AlphaScenario(TM) executed. id,
  organization_id (nullable FK to `organizations`), scenario_name, scenario_description,
  base_scenario_ids (jsonb — the named `risk_service.scenarios.SCENARIOS` entries composed
  into this run), price_shock_pct, demand_shock_bcf_d, supply_shock_bcf_d,
  volatility_multiplier (the composed shock actually applied), portfolio_pnl, strategy_pnl
  (jsonb), margin_impact, var_impact, largest_risk_contributor, requested_by (nullable user
  id), run_at.
- **`alpha_memory_records`** — one row per `MemoryRecord` AlphaMemory(TM) built. id,
  organization_id (nullable FK to `organizations`), memory_type (always `DECISION_MEMORY` in
  Milestone 5), trade_id (nullable — the closed trade this memory was built from), market,
  strategy, title, summary (carries forward `PostTradeAnalysis.lessons` verbatim),
  outcome_quadrant (nullable — carries forward `PostTradeAnalysis.quadrant` unchanged),
  structured_context (jsonb — committee/risk/accuracy/forecast figures), tags (jsonb),
  created_at.
- **`alpha_lesson_proposals`** — one row per `LessonProposal` drafted from a `MemoryRecord`'s
  outcome. id, organization_id (nullable FK to `organizations`), memory_record_id (FK to
  `alpha_memory_records`), proposed_lesson, rationale, status (`PENDING`/`APPROVED`/
  `REJECTED` — the only way it changes is a human review via `POST /alpha/memory/lessons/{id}/
  review`), reviewed_by (nullable), reviewed_at (nullable), created_at.
- **`alpha_market_observations`** — AlphaReplay(TM)'s bitemporal store, one row per *revision* of a
  `TimeSeriesObservation` (docs/alpha-intelligence.md section 9) — an append-only history, never
  updated or deleted in place. id, source, source_type, series_id, symbol (nullable), commodity,
  category, sub_category (nullable), geography (nullable), location (nullable), value, unit,
  observation_time (when the world was in this state), publication_time (when this revision
  became knowable), revision_number, quality_score (nullable), confidence (nullable), metadata
  (jsonb — Python attribute `metadata_`, since SQLAlchemy's declarative `Base` reserves the bare
  `metadata` name), lineage (jsonb), revision_time (nullable — when this revision was recorded,
  distinct from publication_time for the rare case those differ), valid_from (this revision's
  publication_time), valid_to (nullable — `NULL` only for the current/latest revision of a given
  `series_id`+`observation_time`; set to the *next* revision's publication_time when superseded),
  received_time, created_at. `list_market_observations_as_of(series_id, as_of, limit)` is the
  bitemporal "as known at `<as_of>`" query: `publication_time <= as_of AND (valid_to IS NULL OR
  valid_to > as_of)`.
- **`alpha_intelligence_briefs`** — one row per generated `IntelligenceBrief`, the Overnight
  Intelligence Brief (docs/alpha-intelligence.md section 10). id, organization_id (nullable FK to
  `organizations`), market, period_start, period_end, headline, summary, top_signals (jsonb —
  embedded `Signal` snapshots, the same pattern as `ImpactAnalysisRow.chain`, not foreign keys:
  a brief is a point-in-time digest that shouldn't reflect edits made after it was generated),
  top_impacts (jsonb), consensus_highlights (jsonb), notable_scenario_runs (jsonb),
  pending_lessons (jsonb), generated_at.

## 5. TimescaleDB Specifics

- Hypertables: `observations`, `market_ticks`, `gas_balance_daily`, `weather_demand_impacts`.
- Continuous aggregates: daily HDD/CDD rollups, daily balance summary, daily P&L.
- Retention/compression policies are defined in migrations but set to generous defaults in dev.
