# AlphaGasIQ — Powered by Elavo AI — System Architecture

> Product name is a placeholder. All branding lives in `packages/config/branding.ts` /
> `packages/config/branding.py` so it can be renamed without touching business logic.

## 1. Purpose and Guardrails

AlphaGasIQ is an **agentic decision-support and paper-trading platform** for North American
natural gas, with a data model designed to extend to LNG, TTF, JKM, and power markets.

Non-negotiable guardrails baked into the architecture:

1. **No live order routing.** The execution layer is defined behind an `ExecutionAdapter`
   interface. The only implementation shipped initially is `PaperExecutionAdapter`. A future
   `LiveBrokerExecutionAdapter` can be added only after independent model validation, legal /
   compliance review, credentialing, and explicit human + risk sign-off — none of which this
   codebase can grant itself.
2. **The Risk Governor has absolute veto authority.** It is a deterministic, non-LLM rules
   engine. No agent, committee, or LLM call can override a failed hard risk rule. If the Risk
   Governor service is unavailable, the platform fails closed (blocks new risk-taking).
3. **Every decision is auditable.** Every agent output, trade idea, committee decision, risk
   check, and human action is persisted as an append-only record with data lineage back to the
   source observations that informed it.
4. **This is inspired by, and does not copy, any proprietary methodology of any real commodity
   trading firm.** No proprietary CCI (or any other firm's) data, algorithms, or systems are
   used or claimed.

## 2. High-Level System Diagram

```
                                   ┌────────────────────────────┐
                                   │        apps/web (Next.js)   │
                                   │  Dashboard · AI Trader Chat │
                                   └───────────────┬─────────────┘
                                                    │ HTTPS/JSON, WebSocket
                                   ┌───────────────▼─────────────┐
                                   │        apps/api (FastAPI)    │
                                   │  AuthN/Z · REST · WS gateway │
                                   └───┬───────┬───────┬─────────┘
              ┌───────────────────────┘       │       └───────────────────────┐
              │                               │                               │
   ┌──────────▼──────────┐       ┌────────────▼────────────┐      ┌───────────▼───────────┐
   │ services/agents      │       │ services/quant           │      │ services/risk          │
   │  Chief Trading Agent │◄─────►│  Forecast/Regime/RV/     │◄────►│  Risk Engine +         │
   │  Fundamental/Market/  │       │  Backtesting             │      │  Risk Governor (hard   │
   │  Strategy/Committee   │       └──────────────────────────┘      │  deterministic rules)  │
   └──────────┬────────────┘                                         └───────────┬────────────┘
              │                                                                   │
   ┌──────────▼────────────┐   ┌─────────────────────┐   ┌────────────────────────▼──────────┐
   │ services/strategy      │   │ services/paper-      │   │ services/data (provider platform)  │
   │  TradeIdea generation  │──►│  execution            │   │  EIA · NOAA/NWS · FERC · ISO/RTO · │
   │                         │   │  Simulated fills      │   │  SEC EDGAR · News RSS · CME/ICE    │
   └─────────────────────────┘   └─────────────────────┘   │  (mock + real adapters)             │
                                                             └────────────────────┬────────────────┘
                                                                                   │
                                        ┌──────────────────────────────────────────▼─────────────┐
                                        │  Event Bus (Kafka/Redpanda) — canonical domain events    │
                                        └──────────────────────────┬───────────────────────────────┘
                                                                     │
                          ┌──────────────────────────────────────────▼───────────────────────────┐
                          │ PostgreSQL + TimescaleDB (canonical store) · Redis (cache/pubsub) ·    │
                          │ pgvector (embeddings) · S3-compatible object storage (raw payloads)    │
                          └────────────────────────────────────────────────────────────────────────┘

              Temporal orchestrates long-running / durable workflows (ingestion schedules,
              committee debates, storage forecast cycles, paper-trade lifecycle).
```

## 3. Agent Organization

The platform is modeled as an AI commodity-trading firm, not a single monolithic agent. See
`docs/agents.md` for the full roster and the mandatory `AgentResult` contract every agent must
emit. Top-level chain of command:

```
Chief Trading Agent
├── Fundamental Research Team   (Supply, Demand, Storage, Weather, LNG, Pipeline, Power Market)
├── Market Intelligence Team    (Market Data, News Intelligence, Event Detection, Sentiment)
├── Quantitative Team           (Forecasting, Regime Detection, Relative Value, Backtesting)
├── Strategy Team               (Directional, Calendar Spread, Basis, Storage Arb, LNG Arb,
│                                 Volatility, Event)
├── AI Investment Committee     (Bull, Bear, Skeptic, Data Integrity, Portfolio)
├── Independent Risk Org        (Market/Portfolio/Liquidity/Data/Model Risk, Risk Governor)
└── Chief Investment Agent      (receives research + trades; CANNOT override Risk Governor)
```

The Independent Risk Organization is architecturally separate: it runs as its own service
(`services/risk`), is invoked out-of-band of the Chief Investment Agent's reasoning, and its
Risk Governor verdict is the last function call before anything reaches
`APPROVED_FOR_PAPER_TRADING`. No agent process can write a trade past a `BLOCK`/`REJECT`/`HALT`
verdict — this is enforced at the database/service layer, not merely by convention.

## 4. Event-Driven Architecture

All cross-service communication is via typed domain events (see `packages/schemas/events.py`)
published to Kafka/Redpanda topics, one topic family per domain
(`market.*`, `weather.*`, `pipeline.*`, `lng.*`, `news.*`, `storage.*`, `trade.*`, `risk.*`,
`position.*`). Services subscribe only to the topics they need. Every event carries:

- `event_id`, `event_type`, `occurred_at`, `published_at`
- `source_service`, `schema_version`
- `payload` (typed per event, canonical schema)
- `lineage_ids` (upstream observation/event ids that produced this event)

Temporal workflows drive multi-step, stateful processes (e.g. "ingest EIA release → recompute
balance → recompute storage forecast → notify Storage Agent → possibly trigger Strategy Team")
where retries, backoff, and human-in-the-loop signals matter more than raw event fan-out.

The event bus sits behind an `EventBus` interface (`packages/agent-sdk/agent_sdk/eventbus.py`):
`InMemoryEventBus` (the default, `EVENT_BUS_IMPL=memory`) is a pure in-process pub-sub so the
stack boots with `docker compose up`/pytest without requiring a broker at all, and
`RedpandaEventBus` (`agent_sdk/eventbus_kafka.py`, `EVENT_BUS_IMPL=redpanda`) is a real
`aiokafka`-based implementation — works against Redpanda (docker-compose's dev broker, itself
Kafka-API-compatible) or any real Kafka cluster, with no code difference between the two. Both
implement the exact same interface, selected via `agent_sdk.build_event_bus()`, so `AppState`
never needs to know which one it has. `AppState` now actually publishes real `DomainEvent`s
through whichever bus it was built with at every trade-lifecycle transition this platform already
has — `TRADE_IDEA_CREATED`, `RISK_LIMIT_BREACHED`, `TRADE_APPROVED`/`TRADE_REJECTED`,
`POSITION_UPDATED` — rather than the bus existing as unused scaffolding. `RedpandaEventBus` is
tested against faithful `aiokafka` test doubles (`tests/eventbus/test_kafka_eventbus.py`) rather
than a live broker — this sandboxed dev environment has no Docker daemon to run one — but nothing
on this side of that network boundary (topic derivation, JSON (de)serialization via the exact
serializer/deserializer callables passed to the real `aiokafka` classes, one-consumer-task-per-
topic subscribe semantics) is mocked.

## 5. Technology Stack

| Layer | Choice |
|---|---|
| Backend services | Python 3.11+, FastAPI, Pydantic v2 |
| Database | PostgreSQL 16 + TimescaleDB extension |
| Cache / pub-sub | Redis 7 |
| Streaming | Kafka-compatible (Redpanda for dev), abstracted `EventBus` |
| Orchestration | Temporal (durable workflows), abstracted behind `WorkflowEngine` for MVP |
| Frontend | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS |
| Charting | TradingView Lightweight Charts; Mapbox/deck.gl for the pipeline map |
| AI | Anthropic Claude via `packages/agent-sdk/llm.py` `LLMProvider` interface |
| ML | scikit-learn, XGBoost, LightGBM, statsmodels — all real and in use in `services/quant`; PyTorch (TFT/LSTM) is interface-only, not yet implemented |
| Vector/search | pgvector |
| Object storage | S3-compatible (`boto3`, MinIO in dev) |
| Containerization | Docker / docker-compose (dev), designed for AWS (ECS/EKS) in prod |

Cloud dependencies are isolated behind small interfaces (`ObjectStore`, `SecretsProvider`,
`EventBus`) so AWS-specific implementations can be swapped for local/dev equivalents.

## 6. Monorepo Layout

```
/apps
  /web              Next.js dashboard + AI Trader Chat UI
  /api              FastAPI gateway (auth, REST, WebSocket)
/services
  /data             Provider abstraction + connectors (EIA, NOAA, FERC, ISO/RTO, SEC EDGAR,
                     news RSS, CME/ICE adapters, all with Mock* equivalents)
  /agents            Agent runtime + all agent implementations (fundamental, market intel,
                     strategy, investment committee, Chief Trading/Investment Agents)
  /market-data       Market data normalization, continuous contracts, curve construction
  /news              News ingestion pipeline (dedupe, classify, event extraction)
  /weather           Weather ingestion, HDD/CDD calc, model-run delta engine
  /fundamentals      Natural gas balance engine, storage forecasting, LNG/power-burn engines
  /quant             Forecasting, regime detection, relative value, backtesting
  /strategy          Strategy engine producing TradeIdea objects
  /risk              Risk Engine + deterministic Risk Governor
  /paper-execution   Simulated execution engine + portfolio accounting
/packages
  /schemas           Canonical Pydantic models + event contracts shared across services
  /agent-sdk         BaseAgent, AgentResult, LLMProvider, EventBus interfaces
  /data-sdk          BaseDataProvider, DataClassification, ProviderRegistry
  /ui                Shared React components / design tokens for apps/web
  /config            Branding + environment configuration
/infrastructure       Docker, docker-compose, IaC placeholders, migration tooling
/research              Notebooks / offline model research (not imported by services)
/tests                 Cross-service integration tests
/docs                  This documentation set
```

## 7. Data Classification

Every observation and connector is tagged with exactly one of:

- **PUBLIC** — freely available government/public data (EIA, NOAA/NWS, FERC, SEC EDGAR, ISO/RTO
  public feeds).
- **LICENSED** — commercial data requiring an entitlement (CME, ICE, licensed news wires).
  Ships as an adapter interface + `Mock*Provider`; real credentials are opt-in via `.env`.
- **USER_PROVIDED** — data a human uploads or pastes into the platform.
- **SIMULATED** — synthetic/seed data used so the platform is fully demoable with zero paid
  subscriptions. Always visually flagged in the UI.

See `docs/data-sources.md` for the full connector list and `docs/database-schema.md` for the
canonical observation schema that carries this classification through the system.

## 8. Milestone Sequencing

Implementation proceeds in the 11 milestones defined in the product brief (repo/db/auth/shell →
ingestion → fundamentals → agents → quant → strategy/committee → risk → paper execution → chat →
pipeline twin → post-trade learning). Each milestone ships with tests, docs updates, and a
logical commit; later milestones intentionally stub interfaces defined earlier (e.g. the
`LiveBrokerExecutionAdapter` — deliberately never built without independent model validation,
legal/compliance review, and explicit human + risk sign-off, since this platform never routes
live orders) rather than building them speculatively ahead of need. The Kafka-backed `EventBus`
(`RedpandaEventBus`) is no longer one of those stubs — see "Event-Driven Architecture" above.

Milestones 10 and 11 are now implemented at MVP depth alongside 1-9:

- **Milestone 10 (pipeline digital twin)**: `services/fundamentals/fundamentals_service/pipeline_graph.py`
  models ~30 nodes across every node type (production basins, processing plants,
  interconnects, storage, city gates, power plants, LNG terminals, Mexico export points, hubs)
  and ~27 edges across every edge type, with capacity/scheduled-flow/actual-flow/utilization/
  maintenance/constraint/basis-relationship fields. A `PipelineAgent` (Fundamental Research
  Team) surfaces constrained corridors and active maintenance. The frontend map
  (`apps/web/components/pipeline-map/PipelineMap.tsx`) is a dependency-free inline-SVG network
  view — no Mapbox token required — click a node to open `PipelineNodeInspector`.
  **Neo4j-backed pipeline graph**: `pipeline_graph.py`'s in-memory `PipelineGraph` stays the
  app-facing model (no router changes), but `fundamentals_service/pipeline_graph_neo4j.py` adds a
  real round trip through Neo4j behind it — `seed_neo4j_from_graph()` writes every node/edge via
  Cypher `MERGE` (idempotent; safe to re-run every boot), `load_pipeline_graph_from_neo4j()` reads
  them back and reconstructs an equivalent `PipelineGraph`. `AppState` uses this round trip
  (`sync_pipeline_graph_via_neo4j()`) only when `NEO4J_URI` is configured — the same additive,
  config-gated pattern as `OIDC_ISSUER_URL`/`EVENT_BUS_IMPL=redpanda`; every default dev/docker
  environment leaves it unset and keeps the plain in-memory graph, and a Neo4j sync failure at
  boot falls back to it rather than crashing the app. `docker-compose.yml`'s `neo4j` service sits
  behind a Compose profile (`docker compose --profile neo4j up`) so it isn't pulled/started by
  default. No live Neo4j server is reachable in this sandboxed dev environment (no Docker daemon,
  and the egress policy blocks fetching Neo4j's distribution directly), so this is validated
  against faithful `neo4j.AsyncDriver`/`AsyncSession` test doubles
  (`tests/fundamentals/test_pipeline_graph_neo4j.py`) — the same validation posture as
  `RedpandaEventBus` above, for the same reason.
- **Milestone 11 (post-trade learning)**: `services/paper-execution/paper_execution_service/post_trade.py`
  generates a `PostTradeAnalysis` on every position close (`POST /trade-ideas/{id}/close`),
  scoring thesis/timing/risk accuracy and classifying the outcome into one of the four
  decision-vs-outcome quadrants — deliberately never conflating "was this profitable" with "was
  this well-reasoned." `AppState.model_performance_summary()` (`GET /models/performance`)
  aggregates closed trades by strategy for the model-performance dashboard.
- **Quant/post-trade unification**: `AppState.submit_trade_idea()` attaches the Quantitative
  Team's current `PriceForecast` for a trade's instrument at creation time
  (`AppState.trade_forecasts`); `close_trade()` passes it into `evaluate_post_trade()`, which adds
  `quant_model_type`/`quant_predicted_return`/`quant_forecast_error`/`quant_up_probability` to the
  `PostTradeAnalysis` — direction-adjusted so they're comparable to the trade's own actual return,
  independent of the strategy-level thesis/timing/risk scores computed alongside them.
  `model_performance_summary()`'s `quant` section then reports each model's walk-forward-backtested
  directional accuracy (`self.latest_backtests`) side by side with its *live* directional accuracy
  and Brier score computed from closed trades — using the exact same
  `quant_service.metrics.directional_accuracy`/`brier_score` functions the backtester itself uses,
  so a model's backtested and live skill are directly comparable rather than two unrelated numbers.

Milestone 5 (quantitative platform) is also implemented at MVP depth:

- **`services/quant`**: a point-in-time-correctness module (`pit.py` — the platform's most
  load-bearing anti-look-ahead-bias guarantee, since every forecast/backtest depends on it), a
  `ForecastModel` interface with eight real implementations — naive persistence, OLS linear
  trend, ARIMA(2,1,0) (`statsmodels`, with a fallback order ladder for near-degenerate windows),
  VAR (`statsmodels`, fit on a genuine 2-variable system derived from the series itself — price
  level + first difference — so a model that is inherently multivariate still fits the same
  univariate `fit(x, y)` interface every model is judged by, without giving it privileged access
  to a second real-world series the pipeline doesn't otherwise feed into model fitting), a
  state-space local-level Kalman filter model (`statsmodels.tsa.statespace.structural
  .UnobservedComponents`), and Random Forest/XGBoost/LightGBM (`scikit-learn`/`xgboost`
  /`lightgbm`, via a shared lag-feature-plus-recursive-forecast base class in
  `models/tree_ensemble.py`) — plus an honest `NotImplementedModel` stub for the two model types
  the brief names that remain unbuilt (Temporal Fusion Transformer, LSTM — `GET /quant/models`
  reports which are real). Tree-model hyperparameters (`n_estimators`, `n_jobs=1`) and the
  automatic research cycle's own walk-forward `step_days` are deliberately tuned for the
  repeated-small-fit regime walk-forward backtesting runs in (dozens of folds, tens of rows per
  fit) rather than a single large production fit — `n_jobs=-1` measured ~19s for one 37-fold
  Random Forest backtest here purely from repeated multiprocess-pool startup overhead, vs. ~1s at
  `n_jobs=1`. A metrics module (MAE, RMSE, directional accuracy, hit rate, profit factor,
  Sharpe, Sortino, max drawdown, Brier score), a multi-horizon forecast engine, a deterministic
  regime-detection engine (news/weather/storage-shock priority over a plain volatility read,
  matching the `Regime` enum), a relative-value engine (HH-TTF netback + M1-M2 calendar spread
  vs. an illustrative cost-of-carry), and a walk-forward backtesting engine that only ever sees
  what `pit.as_of_filter` says was knowable at each fold — proven by a synthetic price history
  seed that deliberately includes late-published revisions and a regression test asserting they
  are excluded/included at exactly the right moment.
- The Quantitative Team agents (`services/agents/agents_service/quant/`) wrap these engines:
  Forecasting, Regime Detection, Relative Value, and Backtesting agents, all wired into the
  Chief Trading Agent's research cycle and exposed via `/quant/*` endpoints.
- See "Quant/post-trade unification" above for how post-trade scoring and model-performance
  aggregation now draw on this framework rather than living as disconnected heuristics.

Several follow-up hardening items from the MVP status are now closed out:

- **Persistence**: `AppState` (`apps/api/api_app/state.py`) is no longer purely in-memory. A new
  `packages/db` package (`db/models.py`, `db/engine.py`, `db/repository.py`) adds an async
  SQLAlchemy 2.0 `SqlAppRepository` mirroring the trade-idea/committee-decision/risk-check/
  approval/decision-journal/post-trade-analysis/risk-limits tables from
  `infrastructure/db/migrations/001_init.sql`. `AppState`'s existing in-memory dicts stay the
  router-facing read path (zero router changes for read paths); every mutation
  (`submit_trade_idea`, `close_trade`, `persist_approval`, `set_risk_limits`) additionally writes
  through to the repository, and `_hydrate_from_repo()` reloads everything durable at boot before
  the demo research cycle runs — so trade ideas, approvals, and post-trade analyses survive a
  process restart. `config.Settings.database_url` already selected the right DB per environment
  (sqlite file for `uvicorn --reload`, real Postgres via `DATABASE_URL` in docker-compose);
  `conftest.py` now forces `sqlite+aiosqlite:///:memory:` (with `StaticPool`) for the test suite so
  every `AppState()` instance gets a fully isolated database. Validated directly against a live
  local Postgres 16 instance via `asyncpg` — that validation caught a real bug (mixed naive/aware
  datetimes, silently tolerated by sqlite but rejected by `asyncpg`'s stricter encoder), fixed by
  `db.repository._naive_utc()`. See `tests/db/test_repository.py`.
- **Next.js upgrade**: `apps/web` moved from Next 14.2.35/React 18.3.1 (which still carried
  advisories fixable only by a major bump) to Next 16.3.3/React 19.2.8 — `npm audit` now reports
  zero vulnerabilities. The app has no dynamic routes/`params`/`searchParams`/middleware, so the
  usual Next 15/16 breaking changes (async route params, caching defaults) had nothing to touch;
  `tsconfig.json`'s `jsx: react-jsx` was mandatorily migrated by Next's own tooling. Verified with a
  full manual browser pass (every route, plus the sign-in → approve interactive flow) against the
  live API, not just `next build`.
- **Auth: real OIDC**: `apps/api/api_app/oidc.py` adds a real Authorization Code + PKCE flow
  (`GET /auth/oidc/login`, `GET /auth/oidc/callback`) behind the existing dev-mode password-grant
  login — active only when `OIDC_ISSUER_URL`/`OIDC_CLIENT_ID`/`OIDC_CLIENT_SECRET`/
  `OIDC_REDIRECT_URI` are configured (every default dev/docker-compose environment leaves them
  unset, so `GET /auth/mode` reports `oidc_configured: false` and the dev login keeps working
  unchanged). The callback validates the ID token's signature against the IdP's live JWKS
  (`PyJWKClient`), checks issuer/audience/nonce (replay protection), and maps a configurable
  claim (`OIDC_ROLES_CLAIM`, default `"roles"`) onto this platform's own `Role` enum — unrecognized
  claim values fall back to `VIEWER`, never an elevated role. The resulting session is an ordinary
  `create_access_token()` JWT, so `require_role`/`get_current_user` and every router are completely
  unaware whether a session came from SSO or dev login. `apps/web`'s `AuthWidget` shows a "Sign in
  with SSO" option only when `GET /auth/mode` reports it configured; `auth-context.tsx` picks the
  session token up from the callback's redirect URL fragment. See `tests/api/test_oidc.py` for the
  full mocked-IdP round trip (real PKCE verifier/challenge matching, real RS256 signature
  verification via a test keypair, and negative tests proving a nonce mismatch or wrong signing
  key is rejected).
- **Data connectors: ISO/RTO and SEC EDGAR are now real**: `services/data/data_service/
  providers/iso_rto.py` (`ISORTOProvider`) pulls EIA-930 hourly natural-gas-fueled generation for
  PJM/CAISO/ERCOT/MISO/SPP via EIA's own v2 API (reusing the exact auth/request shape
  `EIAProvider` already proves correct, rather than each ISO's own bespoke market-data API);
  `providers/sec_edgar.py` (`SECEdgarProvider`) pulls recent 8-K/10-K/10-Q filings for a tracked
  list of natural-gas-relevant public companies from SEC EDGAR's `submissions` API — genuinely
  free, no API key, just a descriptive contact per SEC's fair-access policy
  (`SEC_EDGAR_CONTACT_EMAIL`). `FERC_PUBLIC` and `PIPELINE_BULLETIN_BOARD` deliberately remain
  `NotImplementedProvider` stubs: neither FERC eLibrary nor per-pipeline electronic bulletin
  boards expose a single stable, well-documented public JSON API the way EIA/NOAA/SEC EDGAR do,
  and this sandboxed environment's egress policy also blocks reaching any of these hosts directly
  to verify request shapes live — an honest `not_configured` stub beats a plausible-looking but
  unverified connector. See `tests/data/test_providers.py` for the new connectors' tests.
- **Access model, Milestone 1 (public site + magic-link UI shell)**: AlphaGasIQ is a private,
  admin-provisioned platform — see `docs/access-model.md` for the full account-lifecycle and
  RBAC/entitlement design (built out across Milestones 2-4). This milestone lays the frontend
  groundwork only: `/` is now the public marketing site (`apps/web/app/page.tsx`), and the
  authenticated trading dashboard that previously lived at `/` has moved to `/platform`
  (`apps/web/app/platform/*`, formerly the `(dashboard)` route group plus the top-level
  `chat`/`pipeline-map`/`model-performance` routes — nesting them under `platform/` also fixed a
  pre-existing bug where those three pages weren't wrapped by the shared header/sidebar layout).
  `/login` replaces the dev-mode credential dropdown as the primary entry point with an
  email-only "Send Secure Magic Link" form; `/contact` is a public business-inquiry form. Per the
  spec's core invariant, there is no `/signup`, `/register`, or `/request-access` route, and
  `POST /contact` persists only to a standalone `ContactInquiry` table with no code path to a
  `User`/`Organization`/session — see `tests/api/test_api.py::test_contact_form_never_creates_a_user_or_session`.
  `POST /auth/magic-link/request` exists now as an honest placeholder: it already implements the
  final non-enumerating response contract (identical generic response for any email), but real
  token issuance and email dispatch don't exist until Milestone 3. The existing dev-mode password
  login (`_DEV_USERS`) is intentionally left in place through Milestone 2 so the platform stays
  usable during the transition; it will be removed once Milestone 3's real magic-link auth lands,
  since a standing password grant would directly conflict with the "no plaintext passwords"
  requirement.
- **Access model, Milestone 2 (admin-provisioned User/Organization/RBAC seed data)**:
  `packages/db/db/models.py` adds `OrganizationRow`/`UserRow`/`RoleRow`/`PermissionRow`/
  `RolePermissionRow`. `SqlAppRepository.seed_rbac_defaults()` idempotently seeds the 8 fixed
  roles and the full permission-key list (with a reviewable default role→permission mapping) on
  every boot. `apps/api/api_app/routers/admin_users.py` is the platform's only `User`-row writer:
  `POST /admin/users` (admin-create, org lookup-or-create-inline, always starts `INVITED`),
  `GET/POST /admin/organizations`, `GET /admin/users(/{id})`, and
  `POST /admin/users/{id}/status` (the account-state machine in the new
  `apps/api/api_app/account_states.py` — see `docs/access-model.md` §2). Every `/admin/*`
  endpoint is gated by today's dev-mode `require_role(Role.ADMIN)` as an interim mechanism; the
  DB-backed `admin.users.create`-style permission check the spec calls for lands in Milestone 4
  once there's a session/user-identity bridge between a JWT and a `UserRow` (Milestone 3).
- **Access model, Milestone 3 (email service, real magic-link auth, sessions)**:
  `apps/api/api_app/email_service.py` adds an `EmailProvider` abstraction — `ConsoleEmailProvider`
  (default everywhere, logs instead of sending — the platform's usual honest-stub pattern) and a
  real `SMTPEmailProvider`, config-gated by `SMTP_HOST` exactly like OIDC/Neo4j/redpanda. `/auth/
  magic-link/request` and a new `GET /auth/magic-link/verify` are now real: `MagicLinkTokenRow`/
  `SessionRow` (`packages/db`) back single-use, hashed-at-rest tokens and revocable sessions.
  Sessions ride a `sid` JWT claim (not `sub`, which stays the stable `user_id`) — `auth.py`'s
  `decode_access_token` only touches the DB when `sid` is present, so dev-mode/OIDC tokens are
  byte-for-byte unaffected. `auth.py::map_db_role_to_dev_roles` bridges the 8 seeded DB roles to
  today's 5-value dev-mode `Role` enum until Milestone 4's real permission enforcement lands. The
  dev-mode password grant (`_DEV_USERS`) is **not** removed as earlier planning assumed — it's
  kept permanently as the platform's fixed bootstrap/break-glass credential set, since something
  has to authenticate the first administrator before any `UserRow` exists to create more; see
  `docs/access-model.md` §3 "Bootstrap credentials" for the full reasoning. `apps/api/api_app/
  rate_limit.py` adds an in-memory sliding-window limiter for the magic-link request endpoint.
- **Access model, Milestone 4 (real RBAC + feature entitlements)**: `apps/api/api_app/
  entitlements.py` resolves a live effective-permission set for any authenticated `User` —
  dev-mode, OIDC, or magic-link alike — by unioning `RolePermission` grants across every role the
  user carries (safe because every dev-mode `Role` enum value is string-identical to a real DB
  role name — see `docs/access-model.md` §4a). `require_permission(...)`/`require_any_permission(...)`
  (FastAPI dependencies) and `ensure_permission(...)` (a plain-function check for mid-handler use)
  replace `admin_users.py`'s placeholder `require_role(Role.ADMIN)` with the exact `admin.*`
  permission the access-model spec assigns each action — verified not to regress any Milestone
  2/3 authorization test. `packages/db` adds `FeatureRow`/`RoleFeatureEntitlementRow`/
  `OrganizationFeatureEntitlementRow`/`UserFeatureOverrideRow` (seeded by
  `SqlAppRepository.seed_feature_defaults()`, 18 features from spec §24); `entitlements.py::
  get_effective_features` computes `globally_enabled AND role_grants AND org_grants AND NOT
  user_denied`, with `security_sensitive` features getting deny-only user overrides. `GET /auth/
  me/entitlements` exposes both for Milestone 5's dashboard/chat integration to consume;
  `require_feature(...)` exists but isn't wired to a user-facing route yet.
- **Access model, Milestone 5 (chat authorization + dashboard entitlement enforcement)**:
  `POST /chat/sessions/{id}/messages` now requires `chief_agent.chat` (spec §26); session
  creation stays open to anonymous exploration. `apps/api/api_app/chat_agent.py::ChatAgent.ask`
  additionally checks a per-topic permission (`_TOOL_PERMISSIONS`) before dispatching to any
  tool — a portfolio/scenario question requires `portfolio.view`, matching spec §28's own
  example; a declined topic never touches `AppState` or calls the LLM. Chat conversations now
  persist to `ChatConversationRow`/`ChatMessageRow` (`packages/db`) behind the existing
  in-memory `ChatSession`/`ChatMessage` contract, with `GET /chat/conversations(/{id}/messages)`
  giving `admin.audit_logs`-holders visibility (spec §29). `GET /portfolio/*` and
  `GET /risk/portfolio` now require the `portfolio_analytics`/`risk_analytics` feature
  entitlements (`require_feature`) — a deliberately scoped slice of spec §25's "both UI and
  backend must enforce entitlements," covering the two areas the spec calls out by example
  rather than a full retrofit of every dashboard endpoint. `RiskSummaryCard.tsx` moved from a
  Server Component to a client component to reach the browser-held session token; `PositionsPanel.tsx`'s
  data fetch was updated to send it. Also fixes a real bug caught during this milestone's
  development: `entitlements.py`'s permission/feature resolution now reads a magic-link user's
  *actual* `UserRow.role_id`, not the route-gating `map_db_role_to_dev_roles` bridge — the bridge
  was silently under/mis-granting `SUPER_ADMIN`/`EXECUTIVE`/`API_USER` magic-link sessions (see
  `docs/access-model.md` §5 for the full explanation and its regression tests).
- **Access model, Milestone 6 (admin console)**: a real admin console at
  `apps/web/app/platform/admin/*` (Overview/Users/Organizations/Features/System Settings),
  backed by a new `apps/api/api_app/routers/admin_console.py` plus extensions to
  `admin_users.py`. `GET /admin/overview` (spec §31) reports real user/org/chat/paper-trading
  metrics, honestly marking fields that depend on not-yet-built subsystems (model health, risk
  alerts, audit-based failed-auth tracking) as `null` in a `not_yet_available` list.
  `PATCH /admin/users/{id}` and `PATCH /admin/organizations/{id}` are partial-update endpoints
  covering spec §32's "Edit user profile"/"Change organization"/"Change role"/"Change data
  entitlements". Feature management (spec §34) gets full CRUD across all four tiers — global
  (`PUT /admin/features/{key}`), role (`PUT /admin/roles/{role}/features/{key}`), organization,
  and per-user (`PUT /admin/users/{id}/features/{key}`, gated by `admin.users.features`) — all
  respecting the deny-override rule for `security_sensitive` features already established in
  Milestone 4. System configuration (spec §38) adds `SystemSettingRow`/`SystemSettingHistoryRow`
  (`packages/db`) behind `GET/PUT /admin/settings(/{key})`, gated by `admin.system_settings`
  (`SUPER_ADMIN`-only) — every write appends the setting's prior value/version to history first,
  giving the "versioned, timestamped, reversible" guarantee the spec calls for without waiting on
  Milestone 10's full `AuditEvent` table.
- **Access model, Milestone 7 (data-feed administration + health + dependency mapping)**: a new
  `apps/api/api_app/routers/admin_data_feeds.py`, gated by `admin.data_feeds`, exposes
  `GET/PATCH /admin/data-feeds(/{provider_id})`, `POST .../test-connection`, `POST .../refresh`,
  `GET .../events`, and `GET /admin/data-feeds/dependency-map` (spec §§35-37). `DataFeedConfigRow`
  (`packages/db`) holds the admin-editable knobs — enabled/paused/polling frequency/freshness
  threshold/priority/fallback provider/notes — seeded one row per registered provider at boot,
  idempotently. It **has no credential/secret field**: every provider's API key stays
  environment-provisioned via `packages/config/config/settings.py` and never enters the database
  or this admin surface, the strongest possible reading of "credentials must never be redisplayed
  after entry." `GET /admin/data-feeds` merges that config with each provider's *live*
  `health_check()` result and a new static dependency map
  (`apps/api/api_app/data_feed_dependencies.py`, built from `docs/agents.md` §2's real agent org
  chart — NOAA's chain is the spec's own worked example verbatim). Test-connection/manual-refresh
  actions call the provider's real `health_check()`/`fetch()` and log a `DataFeedEventRow`; a
  provider exception is recorded as an `error` event, never raised as a 500, since a feed failing
  is expected/normal for this platform's intentionally-stubbed connectors (FERC, pipeline bulletin
  boards, licensed news, live CME/ICE). `GET /admin/overview`'s `data_feed_health`/
  `stale_data_feeds` fields, `null` since Milestone 6, are now computed from this real data.
- **Access model, Milestone 8 (AI Agent Control Center)**: a new
  `apps/api/api_app/routers/admin_agents.py`, gated by `admin.agent_management`, exposes
  `GET /admin/agents(/{agent_type})`, `PATCH /admin/agents/{agent_type}`, and
  `POST /admin/agents/{agent_type}/run` (spec §39). A new `apps/api/api_app/agent_catalog.py`
  centralizes the org-chart data (`team`/`purpose`/`business_functions`/`implemented`/
  `administrable`) that `routers/agents.py`'s pre-Milestone-8 org-chart endpoint previously
  defined inline, so both endpoints share one definition. `GET /admin/agents` merges that catalog
  with each implemented agent's live `model_provider`/`model` (read straight off its real `llm`
  provider instance), real execution statistics computed from `AgentResult`s already in
  `AppState.agent_execution_log`, and its admin-editable operational config (`AgentConfigRow`,
  `packages/db` — status/thresholds/notes, seeded one row per implemented agent at boot). The
  Risk Governor is included for visibility only (no `AgentConfigRow`, no admin actions — see
  `docs/agent-governance.md` §1). `POST /admin/agents/CHIEF_TRADING_AGENT/run` reuses the exact
  logic behind the pre-existing `POST /agents/chief-trading/run` (extracted to
  `AppState.run_chief_trading_cycle()` so both routes share it) and now also refuses to run while
  the agent's own status is `PAUSED`/`DISABLED`. Every other implemented seat is composed
  *internally* by the Chief Trading/Investment Agent's own orchestration code with no independent
  entry point today, so running one directly honestly 409s with an explanation rather than faking
  a result. **Post-MVP follow-up**: setting such a sub-agent's status now genuinely gates its
  execution inside the composed cycle too, not just the Control Center's display —
  `ChiefTradingAgent.run_research_cycle()`/`InvestmentCommittee.deliberate()` accept a
  `disabled_agent_types` set that every `AppState` orchestration call site populates from real
  `AgentConfigRow` statuses; a disabled agent's `_execute()` never runs
  (`BaseAgent.skipped_result()` records a real `SKIPPED` placeholder instead), a disabled
  committee member forces `WAIT_FOR_MORE_DATA` (incomplete quorum, fail closed), and disabling the
  Chief Investment Agent forces `ApprovalState.REJECTED` (see `docs/agent-governance.md` §3).
- **Access model, Milestone 9 (agent versioning + prompt editor + optimization workflow)**: a new
  `AgentVersionRow` (`packages/db`) and `apps/api/api_app/routers/admin_agent_versions.py` expose
  `GET/POST /admin/agents/{agent_type}/versions`, `GET .../versions/production`,
  `GET .../versions/{version_id}`, and `POST .../versions/{version_id}/transition` (gated by
  `admin.agent_management`), plus `POST /admin/agents/{agent_type}/optimization/propose` (gated by
  the stricter, `SUPER_ADMIN`-only `admin.agent_optimization`) (spec §§40-42). The status lifecycle
  `DRAFT → TESTING → APPROVED → PRODUCTION → (RETIRED | ROLLED_BACK)` is enforced server-side by
  `SqlAppRepository.transition_agent_version_status` against a fixed transition table — an illegal
  jump (e.g. straight to `PRODUCTION`) is rejected with 400, so no prompt/model change can bypass
  evaluation. Promoting a version auto-retires the agent_type's prior `PRODUCTION` row; approving
  one records `approved_by`/`approved_at` against the calling administrator. A production agent
  definition is never overwritten — every change creates a new row. `optimization/propose` computes
  a real performance-review snapshot from `agent_execution_log`, requires the admin to state a
  problem/proposed change (no automated LLM-authored proposal yet, a stated scope boundary), and
  creates a `DRAFT` version through the exact same lifecycle every other version uses — there is no
  optimization-specific fast path to production. At boot, every implemented, administrable agent is
  given a real `PRODUCTION` version snapshotted from its actual live configuration
  (`AppState._seed_initial_agent_versions()`), so the system starts populated with the truth. As
  documented plainly in `AgentVersionRow`'s own docstring: nothing yet wires a version's stored
  config back into how `services/agents` actually executes — promoting a version records the
  approved configuration for governance and future runtime wiring, it does not (yet) change what
  the agent's Python code does when it runs.
- **Access model, Milestone 10 (model management + risk settings + audit logging + system
  health)**: closes out the access-model spec's remaining sections. `ModelDefinitionRow`
  (`packages/db`) and `apps/api/api_app/routers/admin_models.py` (`admin.model_management`,
  `SUPER_ADMIN`-only) track every LLM model available for agent assignment; `SqlAppRepository.
  transition_agent_version_status` (Milestone 9) now additionally refuses to move an
  `AgentVersion` into `APPROVED`/`PRODUCTION` unless its `model_name` matches an `APPROVED`
  `ModelDefinitionRow` — the "an agent may never be configured to use a model that isn't approved"
  boundary, enforced structurally. The one LLM model every agent is actually configured with
  (`AppState.llm.model`) is seeded `APPROVED` at boot so this is satisfiable from a fresh install.
  A new `AuditEventRow` and `apps/api/api_app/audit.py`'s `record_audit_event()` helper back a
  genuinely append-only audit trail (`GET /admin/audit-logs`, `admin.audit_logs`) — no update or
  delete method exists for it anywhere. It's wired into every sensitive action this stream's docs
  already named that has a live endpoint: agent status changes (Milestone 8), agent version
  promotion/rollback (Milestone 9), model status changes and risk-setting changes (this milestone),
  and admin user status changes (Milestone 2) — `before`/`after` snapshots are run through FastAPI's
  `jsonable_encoder` first so `datetime` fields serialize cleanly into the `JSON` column. A new
  `GET/PUT /admin/risk-settings` (`admin.risk_settings`, `SUPER_ADMIN`-only,
  `apps/api/api_app/routers/admin_governance.py`) layers a reason-required, audit-logged admin
  surface on top of the pre-existing `PUT /risk/limits` a `RISK_MANAGER` already uses for
  day-to-day changes — both write the same underlying `RiskLimits`. `GET /admin/system-health`
  rolls up live data-feed/agent/model health, the Risk Governor's status, the event-bus
  implementation, and database connectivity from data this platform already tracks — nothing
  fabricated, and a full graphical pipeline visualization is frontend work building on this
  endpoint, honestly not yet built.

## 9. Alpha Intelligence Layer

A proprietary layer sitting between the Natural Gas Digital Twin (`services/data` +
`services/fundamentals`) and the Specialized AI Agents, so the pipeline is:

```
DATA → NATURAL GAS DIGITAL TWIN → ALPHA INTELLIGENCE LAYER → SPECIALIZED AI AGENTS →
AI INVESTMENT COMMITTEE → CHIEF TRADING AGENT → INDEPENDENT RISK GOVERNOR → HUMAN TRADER
```

Six components plus a Chief Trading Agent integration layer, all documented in full in
`docs/alpha-intelligence.md`:

- **AlphaSignal™** — detects material changes (`services/alpha`). **Implemented (Milestone 1
  of this layer).**
- **AlphaImpact™** — event-to-market causal chain (`services/alpha/alpha_service/
  impact_engine.py`). **Implemented (Milestone 2 of this layer).**
- **AlphaConsensus™ + Agent Alpha Score™** — calibrated, dynamically-weighted multi-agent
  forecast aggregation. **Implemented (Milestone 3 of this layer).**
- **AlphaScenario™** — counterfactual/stress-test engine, extending `services/risk/
  risk_service/scenarios.py`. **Implemented (Milestone 4 of this layer).**
- **AlphaMemory™** — decision/institutional memory. **Implemented (Milestone 5 of this layer).**
- **AlphaReplay™** — bitemporal historical reconstruction ("as-known-at" querying, no
  look-ahead bias). **Implemented (Milestone 6 of this layer, `CURRENT_MODEL_RETROSPECTIVE`
  mode only — see below).**

`docs/alpha-intelligence.md` also covers the Enterprise Data Platform (multi-tenant
`Organization` → `Workspace` → `User`, proprietary data connectors) that lets enterprise
customers combine their own data with this layer — sequenced deliberately *after* the six Alpha
components and the Chief Trading Agent integration (Milestones 8-10), since they deliver real
value against today's shared public/simulated dataset first. Milestone 8 (a `Workspace`/
`EnterpriseDataSource`/`EnterpriseDataset`/`EnterpriseDataEntitlement` foundation plus all six
connector types) is implemented. Milestone 9 (the Alpha Intelligence Layer's own Milestone 9, not the
access-model track's) is also implemented at the application layer: every `/alpha/*` list and
get-by-id endpoint now enforces cross-organization data-visibility correctly
(`resolve_organization_scope`/`record_is_visible`, `apps/api/api_app/entitlements.py`), plus a
`ModelRoutingPolicy`/`RetentionPolicy` governance layer and `organization_id` schema readiness
on the core trading tables — but there is still no database-level Row Level Security backstop,
and `AppState` remains a process-wide singleton (see that doc's section 11 for the exact
built-vs-not-built line). Milestone 10 (the Enterprise Opportunity Engine, an
Enterprise-specific Chief Trading Agent chat integration, and an Enterprise Digital Twin
pipeline overlay) is also implemented — see below.

### AlphaSignal™ (implemented)

`services/alpha/alpha_service/materiality.py`'s `MaterialityEngine` is a deterministic,
non-LLM rules engine in the same design philosophy as `risk_service.governor.RiskGovernor` —
pure function of its input, exhaustively unit-tested (`tests/alpha/test_materiality.py`) — that
scores a candidate signal 0-100 from four weighted components (magnitude, historical rarity via
z-score, confidence, data quality). `alpha_service/signal_detector.py`'s `SignalDetector` is
also pure: it diffs the current research cycle's already-computed fundamental-agent outputs
(Supply/Demand/Storage/Weather/LNG/Power/Pipeline) against the previous cycle's stored
baseline for the same metric, and returns any `Signal` (`packages/schemas/schemas/alpha.py`)
that clears the materiality threshold, plus updated baselines — no DB or event-bus access
happens inside either class; `AppState._run_alpha_signal_detection()` (`apps/api/api_app/
state.py`) owns all I/O (loading/saving `SignalBaselineRow`/`SignalRow` via `SqlAppRepository`,
publishing `SIGNAL_DETECTED`/`SIGNAL_ESCALATED` events). Exposed via `GET /alpha/signals` and
`GET /alpha/signals/{id}` (`admin`/`alpha_signals.view` permission, `alpha_intelligence`
feature), an `AlphaSignalTool` chat topic ("What changed overnight?"), and a new
"Alpha Intelligence" dashboard nav section.

### AlphaImpact™ (implemented)

`services/alpha/alpha_service/impact_engine.py`'s `ImpactEngine` is also pure: given a
`Signal`, it builds a causal chain (`ImpactAnalysis`/`ImpactEdge`, `packages/schemas/schemas/
alpha.py`) from a fixed `ImpactCategory` skeleton selected by the signal's type (fundamentals
get the full 8-stage `PHYSICAL → SUPPLY/DEMAND → STORAGE → REGIONAL → PRICE/CURVE → STRATEGY
→ PORTFOLIO → RISK` chain; market/agent-intelligence/portfolio-level signal types get shorter
skeletons), with per-stage confidence/magnitude decaying from the signal's own
confidence/materiality — explicitly documented on every analysis as a fixed heuristic, not an
independently-modeled per-stage forecast. `AppState._run_alpha_signal_detection()` runs this
immediately after every new signal, publishing `IMPACT_ANALYSIS_CREATED`. Exposed via
`GET /alpha/impacts`/`GET /alpha/impacts/{id}` (`alpha_impacts.view` permission), an
`AlphaImpactTool` chat topic ("Why does it matter?" — the natural follow-up to AlphaSignal's
"What changed overnight?"), and an "AlphaImpact" tab in the Alpha Intelligence dashboard
sub-nav. See `docs/alpha-intelligence.md` section 5 for the full design.

### AlphaConsensus™ + Agent Alpha Score™ (implemented)

`services/alpha/alpha_service/forecast_extractor.py`'s `ForecastExtractor` is pure: it turns
each fundamental/quant agent's already-computed `AgentResult.outputs` into a common
`AgentForecast` (`packages/schemas/schemas/alpha.py`) wherever the source agent's own
single-cycle output already implies a genuine directional read (Storage/Weather/Supply/
Demand/Forecasting/Relative-Value — never LNG/Power/Pipeline, whose single-cycle output is a
level, not a trend). `alpha_service/agent_alpha_score.py`'s `AgentAlphaScoreEngine` is also
pure: the Forecasting agent gets a genuine `BACKTESTED_DIRECTIONAL_ACCURACY` score from the
Quant team's real walk-forward backtests; every other agent gets a `CONFIDENCE_CONSISTENCY_
PROXY` score, explicitly documented as not a historical-accuracy claim (no resolved-outcome
ledger per fundamental agent exists yet — that's AlphaMemory's job, a later milestone).
`alpha_service/consensus_engine.py`'s `ConsensusEngine` aggregates `AgentForecast`s into a
`ConsensusView`, weighting each by `(alpha_score / 100) * forecast_confidence` — never equal-
weighted — same design philosophy as the Risk Governor. `AppState._run_alpha_consensus()`
(`apps/api/api_app/state.py`) runs after the quant research cycle, persisting/publishing
`AgentForecastRow`/`AGENT_FORECAST_CREATED`, `AgentAlphaScoreRow`, and
`ConsensusViewRow`/`CONSENSUS_UPDATED` (or `CONSENSUS_DIVERGENCE_DETECTED` on low agreement) —
including a specialized `STORAGE_FORECAST` view that reproduces the flagship "AlphaConsensus
vs. Market Consensus" Bcf comparison. Exposed via `GET /alpha/consensus`,
`GET /alpha/consensus/{market}`, and `GET /alpha/consensus/by-id/{id}` (`alpha_consensus.view`
permission), an `AlphaConsensusTool` chat topic ("Do the agents agree?" — the natural follow-up
to AlphaImpact's "Why does it matter?"), and an "AlphaConsensus" tab in the Alpha Intelligence
dashboard sub-nav. See `docs/alpha-intelligence.md` section 6 for the full design.

### AlphaScenario™ (implemented)

`services/alpha/alpha_service/scenario_engine.py`'s `ScenarioEngine` is pure: `compose()`
combines named base scenarios from `risk_service.scenarios.SCENARIOS` with custom
`ScenarioVariable` shocks (`packages/schemas/schemas/alpha.py`) into one
`risk_service.scenarios.Scenario` (price/demand/supply shocks summed, volatility multipliers
compounded), then `run()` calls the existing, already-tested `risk_service.scenarios.
run_scenario()` — the P&L/VaR math is never re-implemented. `run_standing_library()` runs
every entry in the standing stress-test catalog in one pass; `compare()` ranks any result set
worst-to-best. `AppState.run_alpha_scenario()`/`run_alpha_scenario_comparison()` persist via
`ScenarioRunRow` and publish `SCENARIO_RUN`/`SCENARIO_COMPARISON_RUN`. Exposed via
`GET /alpha/scenarios/library`, `POST /alpha/scenarios/run`, `POST /alpha/scenarios/compare`,
`GET /alpha/scenarios/runs`/`GET /alpha/scenarios/runs/{id}` (new `alpha_scenarios.view`/
`alpha_scenarios.run` permissions) — additive to, not a replacement for, the pre-existing
`GET /risk/scenarios`/`POST /risk/scenarios/{id}/run` (single named scenario, no composition/
comparison/persistence). The pre-existing `run_named_scenario` chat topic now composes an
explicit percentage shock when one is named in the question; a new `"scenario_comparison"`
topic runs the whole standing library. See `docs/alpha-intelligence.md` section 7 for the
full design.

### AlphaMemory™ (implemented)

`services/alpha/alpha_service/memory_builder.py`'s `MemoryBuilder`/`LessonEngine` are pure:
`MemoryBuilder.build_decision_memory()` assembles a `MemoryRecord` (`packages/schemas/schemas/
alpha.py`) from a closed trade's already-computed `TradeIdea`/`InvestmentCommitteeDecision`/
`RiskCheckResult`/`PostTradeAnalysis` (and its attached `PriceForecast`, if any) — carrying
forward `PostTradeAnalysis.quadrant`/`.lessons` unchanged rather than reclassifying the outcome.
`LessonEngine.propose()` drafts a `LessonProposal` from a fixed template keyed off the memory's
`OutcomeQuadrant` — not an LLM, matching every other Alpha* engine's "no LLM in the engine path"
discipline. `AppState._build_decision_memory()` runs immediately after `close_trade()` persists
its `PostTradeAnalysis`, publishing `MEMORY_RECORD_CREATED`/`LESSON_PROPOSED`;
`AppState.review_lesson_proposal()` is the only way a proposal's status changes, and approving
one never wires it back into any production model or threshold automatically. Exposed via
`GET /alpha/memory`/`GET /alpha/memory/{id}`, `GET /alpha/memory/lessons`/`GET /alpha/memory/
lessons/{id}`, and `POST /alpha/memory/lessons/{id}/review` (new `alpha_memory.view`/
`alpha_memory.review` permissions — the latter narrower, granted only to RISK_MANAGER/
RESEARCHER), a new "what have we learned" chat topic, and a fifth "AlphaMemory" tab in the
Alpha Intelligence dashboard with an inline lesson-review panel. See
`docs/alpha-intelligence.md` section 8 for the full design.

### AlphaReplay™ (implemented)

`packages/schemas/schemas/observation.py`'s `TimeSeriesObservation` gained a full bitemporal
model: pre-existing `observation_time`/`publication_time` (when the world was in a state / when
that became knowable) plus new `revision_time`/`valid_from`/`valid_to` (which revision of a
`series_id`+`observation_time` was the current best estimate at any given moment). `packages/db/
db/repository.py`'s `save_market_observation()` closes out a superseded revision's `valid_to`
rather than overwriting it — append-only — and `list_market_observations_as_of()` is the core
"as known at `<as_of>`" query (`publication_time <= as_of AND (valid_to IS NULL OR valid_to >
as_of)`), proven by `tests/db/test_market_observations.py` to recover exactly what was believed
at a past moment even after a later correction has since been recorded. Every other Alpha* list
method gained an `until` (as-of) filter for the same reason. `services/alpha/alpha_service/
replay_engine.py`'s `ReplayEngine.assemble()` is a thin, pure packaging function — all real
bitemporal correctness lives in the repository queries, not here. `AppState.
compute_as_of_replay()` fetches every Alpha* series as-of a chosen moment and assembles an
`AsOfReplayResult`. Milestone 6 is honest about scope: `mode` is always
`CURRENT_MODEL_RETROSPECTIVE` — a replay of what this already-running system itself recorded at
the time, not a reconstruction of market reality from before Milestone 6 shipped
(`HISTORICAL_REALITY`), not a replay using the agent versions that existed then
(`ORIGINAL_MODEL_REPLAY` — `AgentVersionRow` tracks config snapshots but nothing re-executes an
agent against a past config yet), and not a full re-simulation of the trade lifecycle
(`FULL_STRATEGY_REPLAY`) — all three remain future work. Exposed via `GET /alpha/replay`
(`market`, `as_of`; new `alpha_replay.view` permission), a `"replay_snapshot"` chat topic ("time
machine"/"as of"/"what did we know") — the first Alpha* chat topic whose answer cannot come from
a bounded in-memory cache, so `ChatAgent._dispatch()` became `async def` to let it directly
`await state.compute_as_of_replay()` — and a sixth "AlphaReplay" tab in the Alpha Intelligence
dashboard with an as-of timestamp picker. See `docs/alpha-intelligence.md` section 9 for the
full design.

### Chief Trading Agent full integration (implemented)

Every Alpha* component above ran strictly *after* a `TradeIdea` already existed — a parallel,
downstream analysis layer with no feedback path into trade generation. `services/alpha/
alpha_service/trading_integration.py`'s `AlphaCorroborationEngine` (pure) closes that loop:
`AppState.submit_trade_idea()` — the single choke point every trade idea passes through, in
both `_run_initial_research_cycle` and `run_chief_trading_cycle`, before the Investment
Committee deliberates — cross-checks the trade against fresh AlphaSignal output and the latest
AlphaConsensus view and merges the result onto `trade.catalysts`/`.supporting_data`/
`.source_citations`/`.risks`, so `BullAgent` (reads `catalysts`) and `SkepticAgent` (reads
`source_citations`/`supporting_data`) genuinely see it. `services/alpha/alpha_service/
brief_engine.py`'s `BriefEngine` (also pure, template-based, no LLM) composes the Overnight
Intelligence Brief — a cross-component digest generated once per full research cycle via
`AppState.generate_intelligence_brief()`, exposed via `GET /alpha/briefs/latest`/`GET
/alpha/briefs`/`GET /alpha/briefs/{id}` (new `alpha_brief.view` permission) and a new
`"overnight_brief"` chat topic. A new root page at `/platform/alpha-intelligence`
(`AlphaOverview.tsx`) renders the latest brief plus six link cards tying the layer together; the
top-level nav link now points here instead of straight to `/signals`. See
`docs/alpha-intelligence.md` section 10 for the full design.

### Enterprise Data Platform foundation (implemented — Milestone 8)

A genuine, testable foundation, honest that most of the originally-envisioned scope (real
tenant-isolation enforcement, `ModelRoutingPolicy`, most admin tabs) was still Milestone 9-10
at the time this section was written; Milestone 9 (below) has since closed the tenant-isolation
gap at the application layer and added `ModelRoutingPolicy`/`RetentionPolicy`. `Workspace`/
`WorkspaceMemberRow` (`packages/db/db/models.py`) group users inside an `Organization`.
`EnterpriseDataSourceRow`/`EnterpriseDatasetRow`/`EnterpriseDataEntitlementRow`/
`EnterpriseRecordRow`/`EnterpriseDataEventRow` back an admin-registered connection to a
customer's proprietary data, its registered datasets, dataset-level access grants
(`principal_type` unifies `AgentDataEntitlement` into the same table rather than a parallel
one), ingested rows, and a test-connection/ingest event log. `services/
enterprise_data/enterprise_data_service/connector.py`'s `BaseEnterpriseDataConnector` mirrors
`data_sdk.provider.BaseDataProvider`'s shape (`test_connection`/`discover_schema`/`preview`/
`ingest`/`health_check`); all six `EnterpriseConnectorType` values are implemented end-to-end
(`ManualUploadConnector`/`WebhookConnector` take rows from the request body / an HMAC-verified
inbound-push staging buffer, `enterprise_webhook_staged_rows`; `RestApiConnector`/
`DatabaseConnector`/`S3Connector`/`SftpConnector` pull live via `httpx`/`sqlalchemy`/`boto3`/
`paramiko` from wherever the source's non-secret `connection_config` points, reporting
`not_configured` when required config/credential is missing), the same "must work with zero
paid subscriptions" discipline every `Mock*Provider` already establishes. `EnterpriseDataSourceRow`
deliberately carries no credential field, mirroring `DataFeedConfigRow`'s existing posture —
every connector resolves its actual secret from an environment variable named (never stored) in
`connection_config`. Exposed via `/admin/workspaces(/{id}/members)` and
`/admin/enterprise-data/sources(/{id}/test-connection|/datasets)`/`/admin/enterprise-data/
datasets/{id}(/preview|/ingest|/records|/entitlements)` plus the public, signature-verified
`POST /webhooks/enterprise-data/{source_id}` ingress (new `admin.workspaces`/
`admin.enterprise_data` permissions), plus new "Workspaces" and "Enterprise Data" admin console
tabs. See `docs/alpha-intelligence.md` section 11 for the full built-vs-not-built design.

### Tenant isolation retrofit + model routing/retention policy (implemented — Milestone 9)

Closes the two cross-organization data-visibility gaps Milestone 8's own write-up flagged:
every `/alpha/*` list endpoint previously skipped organization filtering entirely for a caller
whose own organization couldn't be resolved (rather than restricting to platform-wide data),
and every `/alpha/*` get-by-id endpoint performed no organization check at all.
`resolve_organization_scope(user, state) -> (organization_id, unrestricted)`
(`apps/api/api_app/entitlements.py`) replaces `resolve_organization_id` at every Alpha* read
call site; `unrestricted=True` only for a caller with no resolvable organization *and*
`admin.organizations`. Every affected `Repository.list_*` method gained a `platform_only: bool`
parameter, and `record_is_visible(record_org, caller_org, unrestricted) -> bool`
(`apps/api/api_app/entitlements.py`) gates every get-by-id endpoint post-fetch, 404ing (never
403ing) on an invisible record. `tests/api/test_alpha_tenant_isolation.py` proves the fix
end-to-end. Also new: `ModelRoutingPolicy`/`RetentionPolicy`
(`packages/schemas/schemas/enterprise.py`, `model_routing_policies`/`retention_policies`
tables) — per-`(organization_id, EnterpriseDataClassification)` governance rows, with
`organization_id=None` as the platform default. `ModelRoutingEngine`/`RetentionEngine`
(`services/enterprise_data/enterprise_data_service/`) are pure policy-resolution functions;
`PolicyGatedLLMProvider` (`packages/agent-sdk/agent_sdk/llm.py`) is the provider-swapping
enforcement primitive for `ModelRoutingPolicy` — `ChatAgent._enterprise_data_query`, below,
is its live caller: it wraps the final prose-synthesis call in a `PolicyGatedLLMProvider`
gated by the combined decision across every involved dataset, on top of also deciding what
goes into the prompt in the first place (provider-swapping and content-withholding together,
not either/or); `AppState.apply_retention_policy()` is the I/O half of `RetentionPolicy`, purging expired
`EnterpriseRecordRow`s. Both exposed via `/admin/model-routing-policies`/
`/admin/retention-policies(/apply)` (new `admin.model_routing_policy`/`admin.retention_policy`
permissions) — API-only, no admin UI yet. Finally, `trade_ideas`/`committee_decisions`/
`risk_checks`/`approvals` each gained a nullable `organization_id` column, and
`TradeIdea.organization_id` now round-trips onto all four through
`AppState.submit_trade_idea()` — schema readiness only, since every trade idea today still
comes from the single process-wide `AppState`'s system-generated research cycle, never a
per-organization submission path. See `docs/alpha-intelligence.md` section 11.1/11.5/11.6 for
the full built-vs-not-built design, including what real database-level RLS enforcement would
still add on top of this.

### Enterprise Opportunity Engine + Enterprise-specific Chief Trading Agent + Enterprise
Digital Twin overlay (implemented — Milestone 10)

`EnterpriseOpportunity` (`packages/schemas/schemas/enterprise.py`) is a human-reviewed
candidate opportunity — `organization_id` **required**, not nullable, since it's inherently
derived from one organization's own data — drafted by `EnterpriseOpportunityEngine`
(`services/enterprise_data/enterprise_data_service/opportunity.py`, pure, zero I/O): it
cross-references the organization's own `POSITION`/`PORTFOLIO`-domain enterprise records
against recent `Signal`s/`ConsensusView`s and detects two shapes,
`HEDGE_MISALIGNED_POSITION` (a held position runs counter to a high-confidence consensus view)
and `NEW_POSITION_HIGH_CONVICTION_SIGNAL` (a high-materiality directional signal in a market
with no existing position). `AppState.generate_enterprise_opportunities()` does the I/O
(load datasets/records/signals/consensus, run the engine, persist, publish
`OPPORTUNITY_PROPOSED`); `GET/POST /alpha/enterprise/opportunities*`
(`enterprise_opportunities.view`/`.generate`/`.review`) is the API, tenant-isolated via the
same `resolve_organization_scope`/`record_is_visible` helpers Milestone 9 built; a dashboard
tab (`OpportunitiesTable.tsx`) lists/generates/reviews.

`ChatAgent._enterprise_data_query` (`apps/api/api_app/chat_agent.py`, topic
`enterprise_data_query`, gated by new `enterprise_data.query`) is the Enterprise-specific
Chief Trading Agent chat integration: answers using the caller's own organization's registered
enterprise datasets, and is the first real caller `ModelRoutingEngine` has had since Milestone
9 — a dataset whose resolved `ModelRoutingPolicy` denies external LLM processing is named but
its content withheld from the facts handed to `self.llm.complete()`. Also narrowed by
fine-grained per-dataset `EnterpriseDataEntitlement` grants via `filter_entitled_enterprise_
datasets` (`apps/api/api_app/entitlements.py`) — a dataset with no entitlement rows stays
visible to the whole organization, but once at least one grant exists only a matching
principal sees it.

`GET /alpha/enterprise/pipeline-overlay` (`enterprise_data.query`) is the Enterprise Digital
Twin overlay: the same public pipeline graph `GET /fundamentals/pipeline/graph` returns, plus
`overlay.assets` — the caller's own organization's `ASSET`/`FACILITY`-domain enterprise records
that name a real node in the graph, via `PipelineOverlayPoint.from_record`/`build_overlay`
(`services/enterprise_data/enterprise_data_service/pipeline_overlay.py`, pure). The pipeline
map page gained a "Show my enterprise assets" toggle. See `docs/alpha-intelligence.md` section
11.7 for the full built-vs-not-built design.
