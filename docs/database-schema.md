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
  grants; not yet read by any enforcement path (Milestone 4).

## 5. TimescaleDB Specifics

- Hypertables: `observations`, `market_ticks`, `gas_balance_daily`, `weather_demand_impacts`.
- Continuous aggregates: daily HDD/CDD rollups, daily balance summary, daily P&L.
- Retention/compression policies are defined in migrations but set to generous defaults in dev.
