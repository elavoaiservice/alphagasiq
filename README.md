# AlphaGasIQ — Powered by Elavo AI

An institutional-grade **agentic AI natural-gas intelligence & decision-support platform**,
initially focused on North American natural gas (NYMEX Henry Hub futures), built as a
multi-agent trading organization rather than a single monolithic AI.

**This is a decision-support and paper-trading system.** No live order routing is enabled —
the execution layer is a `PaperExecutionAdapter` behind an `ExecutionAdapter` interface; a
future regulated broker/exchange connection can only be added after independent model
validation, legal/compliance review, credentials, and explicit human + risk sign-off. The
deterministic **Risk Governor** has absolute veto authority over every proposed trade; no LLM
can override a failed hard risk rule.

`AlphaGasIQ` is a placeholder product name — see `packages/config/config/branding.py`.

## Start here

- `docs/architecture.md` — system architecture & multi-agent org chart
- `docs/database-schema.md` — canonical data model
- `docs/agents.md` — every agent's contract and responsibilities
- `docs/data-sources.md` — provider abstraction & data classification (PUBLIC/LICENSED/USER_PROVIDED/SIMULATED)
- `docs/risk-framework.md` — the Risk Governor's deterministic rule chain
- `docs/api-specification.md` — REST API surface
- `docs/frontend-component-tree.md` — dashboard component hierarchy
- `docs/access-model.md` — admin-provisioned account lifecycle, magic-link auth, RBAC & entitlements
- `docs/agent-governance.md` — Agent Control Center, versioning/optimization workflow, Risk Governor boundary (design-only; built out in Milestones 8-10)

## Stack

Versions below are the ones actually declared in the repo (`pyproject.toml` /
`apps/web/package.json` / `docker-compose.yml`), not aspirational ones.

**Backend — Python 3.11** (`requires-python = ">=3.11"`, `python:3.11-slim` in
`Dockerfile.api`, `.github/workflows/ci.yml` pins 3.11):

- **FastAPI** `>=0.110` + **Uvicorn[standard]** `>=0.29` — the REST surface and the
  `GET /ws/events` WebSocket.
- **Pydantic v2** `>=2.6` + **pydantic-settings** `>=2.2` — `packages/schemas` is the
  canonical data model; `packages/config` reads every setting from the environment.
- **SQLAlchemy 2.0** (async) — **asyncpg** `>=0.29` against Postgres, **aiosqlite**
  `>=0.19` for the default dev DB and the per-test in-memory DB.
- **PyJWT[crypto]** `>=2.8` — dev-password, magic-link, and OIDC sessions all mint the
  same JWT (the `sid` claim is what makes a session server-side revocable).
- **httpx** `>=0.27` — every data connector (EIA, NOAA, NHC, ISO/RTO, SEC EDGAR, Yahoo).
- **anthropic** `>=0.40` — the Claude agents. Default model `claude-sonnet-5`
  (`packages/agent-sdk/agent_sdk/anthropic_provider.py`); unset `ANTHROPIC_API_KEY`
  falls back to the deterministic mock provider.
- **sentry-sdk** `>=2.0` — imported and initialized only when `SENTRY_DSN` is set.

Per-service additions:

- `services/quant` — **numpy** `>=1.26`, **statsmodels** `>=0.14` (ARIMA/VAR/state-space),
  **scikit-learn** `>=1.4` (Random Forest), **xgboost** `>=2.0`, **lightgbm** `>=4.0`.
- `services/enterprise_data` — **boto3** `>=1.34` (S3) and **paramiko** `>=3.4` (SFTP),
  the two enterprise connectors that are genuinely implemented.
- `services/fundamentals` — the **neo4j** `>=5.0` driver, for the optional pipeline
  digital twin.
- `packages/agent-sdk` — **aiokafka** `>=0.11`, imported only when the event bus is
  actually `EVENT_BUS_IMPL=redpanda`.

**Frontend — Node 20** (`node:20-slim` in `Dockerfile.web`):

- **Next.js 16.3.3** (App Router) on **React 19.2.8** — upgraded from 14/18.
- **TypeScript 5.5.3** — `next build` type-checks in CI.
- **Tailwind CSS 3.4.4** + PostCSS 8.5 + Autoprefixer, carrying the ElavoAI palette.
- **lightweight-charts 4.1.3** — dynamically imported by `ForwardCurveChart.tsx`; the
  pipeline map is dependency-free inline SVG, so there is no Mapbox token to provision.
- No state-management library: one React context (`LiveEventsProvider`) over a shared
  WebSocket, plus `fetch`.

**Infrastructure** (`docker-compose.yml`):

- **TimescaleDB** `timescale/timescaledb-ha:pg16` — `001_init.sql` creates the extension
  and three hypertables (`observations`, `weather_demand_impacts`, `market_ticks`).
  Postgres is also what makes the Row Level Security layer real; SQLite has no equivalent,
  so the RLS suite skips there.
- **Redis** `7-alpine` — started, but **nothing reads it yet**. Magic-link rate limiting
  is an in-process sliding window (`apps/api/api_app/rate_limit.py`); `REDIS_URL` exists
  for the multi-instance deployment that would need it.
- **Redpanda** `v24.1.9` (Kafka API) — only used when `EVENT_BUS_IMPL=redpanda`; the
  default event bus is in-memory.
- **Neo4j** `5-community` — behind the `neo4j` compose profile, so a plain
  `docker compose up` never starts it.
- **CI** — GitHub Actions: pytest (with a `postgres:16` service container backing the
  live RLS suite) and `next build`.

The backend is a **setuptools monorepo of 14 editable-installed local packages** —
nothing is published to PyPI, which is why both the Dockerfile and CI install with the
same explicit `pip install -e ...` ordering.

## Run it

```bash
cp .env.example .env   # optional — every value has a working SIMULATED/mock fallback
docker compose up
```

- API: http://localhost:8000/api/v1 (docs at http://localhost:8000/api/v1/docs is not yet
  wired for the mounted sub-app; use `/api/v1/system/status` as a smoke test)
- Web dashboard: http://localhost:3000
- Dev login users (see `apps/api/api_app/auth.py`): `trader@alphagasiq.local` /
  `trader-dev-password`, `risk@alphagasiq.local` / `risk-dev-password`,
  `admin@alphagasiq.local` / `admin-dev-password`

No paid API keys are required — `EIA`/`NOAA` connectors are real but optional (blank keys
report `not_configured`), and market data / news default to `MockCMEProvider` /
`MockNewsProvider`, always tagged `SIMULATED` end-to-end into the UI.

### Run without Docker

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e packages/schemas -e packages/data-sdk -e packages/agent-sdk -e packages/config \
            -e packages/db -e services/data -e services/fundamentals -e services/risk \
            -e services/paper-execution -e services/agents -e services/quant -e services/alpha \
            -e services/enterprise_data -e apps/api
uvicorn api_app.main:app --reload --app-dir apps/api   # http://localhost:8000

cd apps/web && npm install && npm run dev               # http://localhost:3000
```

## Test

```bash
source .venv/bin/activate
pip install pytest pytest-asyncio
pytest
```

Risk Governor logic (`services/risk/risk_service/governor.py`) carries the highest test
coverage bar in the repo — see `tests/risk/test_governor.py` — per the platform's core rule:
**no LLM may override a failed hard risk rule.**

`.github/workflows/ci.yml` runs the same two checks on every push/PR: the full pytest suite
(same editable-install sequence as above) and `next build` (which includes TypeScript
type-checking) for `apps/web`. The backend job also runs a `postgres:16` service container so
`tests/db/test_rls.py`'s live Row Level Security suite (docs/alpha-intelligence.md section 11.1)
actually exercises real Postgres RLS enforcement on every push, not just once locally; without a
reachable Postgres (e.g. running `pytest` directly against the default SQLite dev database)
those tests skip gracefully instead of failing.

## Repository layout

See `docs/architecture.md` §6. Short version: `/apps` (web, api) · `/services` (agents, alpha,
data, enterprise_data, fundamentals, paper-execution, quant, risk) · `/packages` (agent-sdk,
config, data-sdk, db, schemas) · `/infrastructure` (Docker, DB migrations) · `/docs` · `/tests`.

## Current implementation status

This repo implements all 11 milestones of the phased build plan in `docs/architecture.md` §8
at MVP depth:

- **1-4**: repo/db/auth/dashboard shell, EIA/NOAA/mock-market/mock-news ingestion, the natural
  gas balance + storage forecast + weather-demand engines, the Chief Trading Agent with
  Supply/Demand/Storage/Weather/Pipeline agents.
- **5 (quantitative platform)**: `services/quant` — a point-in-time-correctness module
  (`pit.py`, guarding against the exact EIA-style reporting-lag look-ahead bug the brief calls
  "critical"), eight real forecasting models — naive persistence, OLS linear trend, ARIMA, VAR,
  a state-space (Kalman filter) model, and Random Forest/XGBoost/LightGBM — plus an honest
  `NotImplementedModel` stub for the two model types that remain unbuilt (TFT/LSTM —
  `GET /quant/models` shows which), the metrics module (MAE, RMSE, directional accuracy, hit
  rate, profit factor, Sharpe, Sortino, max drawdown, Brier score), a multi-horizon forecast
  engine, a deterministic regime-detection engine, a relative-value engine (HH-TTF netback +
  calendar spread), and a walk-forward backtesting engine — all wrapped by four Quantitative Team
  agents (Forecasting/Regime Detection/Relative Value/Backtesting) and exposed via `/quant/*`.
- **6-9**: a Directional Strategy Agent, the AI Investment Committee
  (Bull/Bear/Skeptic/Data Integrity/Portfolio), the deterministic Risk Governor, the
  paper-trading engine, and the AI Trader Chat.
- **10 (pipeline digital twin)**: a ~30-node/~27-edge graph across every node/edge type in
  docs/database-schema.md, a `PipelineAgent`, and a dependency-free inline-SVG interactive map
  (no Mapbox token needed) with a click-to-inspect node drawer.
- **11 (post-trade learning)**: closing a paper position (`POST /trade-ideas/{id}/close`, or the
  dashboard's Paper Positions panel) generates a `PostTradeAnalysis` — thesis/timing/risk
  accuracy plus a GOOD/BAD-decision × GOOD/BAD-outcome quadrant that deliberately never
  conflates "profitable" with "well-reasoned" — and `GET /models/performance` aggregates closed
  trades into a model-performance dashboard.

A minimal dev-mode sign-in widget (top-right of the header) and an Approval Queue panel were
added alongside Milestone 11 so the full loop — recommendation → human approval → paper
execution → close → post-trade analysis — is actually exercisable from the UI, not just the API.

**Post-trade learning and the quantitative platform are unified**, not two disconnected
heuristics: when a trade is created, the Quantitative Team's current `PriceForecast` for that
instrument is attached to it; closing the trade scores that forecast (direction-adjusted
predicted return, forecast error, win-probability) alongside the strategy's own thesis/timing/
risk scoring, using the same fields the trade's `TradeIdea` and the model's `PriceForecast` both
carry. `GET /models/performance`'s `quant` section then reports each model's walk-forward-
backtested directional accuracy side by side with its *live* directional accuracy and Brier
score from actual closed trades — computed with the exact same `quant_service.metrics`
functions the backtester uses, so "how well we expected this model to do" and "how well it
actually did" are directly comparable, not two disconnected numbers. See the "Quant/post-trade
unification" note in `docs/architecture.md` §8 for the full mechanism.

**Persistence is now durable, not purely in-memory.** `apps/api/api_app/state.py` still exposes
its in-memory dicts as the router-facing read path, but every mutation now writes through a real
async SQLAlchemy 2.0 repository (`packages/db`) mirroring `infrastructure/db/migrations`, and boot
hydrates from it — trade ideas, approvals, and post-trade analyses survive a process restart.
`config.Settings.database_url` already resolves per environment (sqlite file for
`uvicorn --reload`, real Postgres via docker-compose's `DATABASE_URL`); the test suite forces an
isolated in-memory sqlite DB per test. Validated directly against a live local Postgres instance
(`tests/db/test_repository.py`), which caught and fixed a real naive/aware-datetime bug that
sqlite alone would have masked.

**`apps/web` runs Next.js 16 / React 19** (upgraded from 14/18) — `npm audit` reports zero
vulnerabilities. No dynamic routes existed to hit the usual Next 15/16 breaking changes; verified
with a full manual browser pass (every route, the sign-in → approve flow) against the live API.

**Auth now supports real OIDC** (`apps/api/api_app/oidc.py`) — Authorization Code + PKCE, live
JWKS signature validation, issuer/audience/nonce checks, and configurable-claim role mapping —
active only when `OIDC_ISSUER_URL`/`OIDC_CLIENT_ID`/`OIDC_CLIENT_SECRET`/`OIDC_REDIRECT_URI` are
set; every default dev/docker environment leaves them unset, so the dev-mode password-grant login
above keeps working unchanged (`GET /auth/mode` reports which mode is active). See
`docs/architecture.md` §8 and `tests/api/test_oidc.py` for the full mocked-IdP round trip,
including a real PKCE verifier/challenge and RS256 signature check.

**Six more quant models are now real, not stubs.** `services/quant` implements ARIMA, VAR, a
state-space (Kalman filter) model, and Random Forest/XGBoost/LightGBM alongside the original
naive persistence and OLS linear trend — `GET /quant/models` now reports 8 of the 10 named model
types as implemented; only the two deep-learning types (TFT, LSTM) remain `NotImplementedModel`
stubs. See "Milestone 5 (quantitative platform)" above for the details, including the
walk-forward-backtesting performance tuning these six models needed (tree-model `n_jobs=1`,
tuned `n_estimators`, and the automatic research cycle's coarser `step_days`) and the real,
pre-existing threshold bug this work surfaced and fixed in `DirectionalStrategyAgent`.

**The event bus is real, not unused scaffolding.** `RedpandaEventBus`
(`packages/agent-sdk/agent_sdk/eventbus_kafka.py`, `aiokafka`-based) implements the same
`EventBus` interface as `InMemoryEventBus` and activates via `EVENT_BUS_IMPL=redpanda` (matching
docker-compose's `redpanda` service) — and `AppState` now actually publishes `DomainEvent`s
(`TRADE_IDEA_CREATED`, `RISK_LIMIT_BREACHED`, `TRADE_APPROVED`/`TRADE_REJECTED`,
`POSITION_UPDATED`) through whichever bus it was built with, closing the gap where the bus
existed but nothing published to it. No live broker is reachable in this dev sandbox (no Docker
daemon), so `RedpandaEventBus` is tested against faithful `aiokafka` test doubles
(`tests/eventbus/test_kafka_eventbus.py`) rather than a live one — everything on this side of
that network boundary is real, unmocked code.

**ISO/RTO and SEC EDGAR are now real data connectors, not stubs.** `ISORTOProvider`
(`services/data/data_service/providers/iso_rto.py`) pulls EIA-930 hourly natural-gas-fueled
generation for PJM/CAISO/ERCOT/MISO/SPP through EIA's own v2 API (same proven auth/request shape
as the existing `EIAProvider`); `SECEdgarProvider` (`providers/sec_edgar.py`) pulls recent
8-K/10-K/10-Q filings for tracked natural-gas-relevant public companies from SEC EDGAR — no API
key needed, just a contact email per SEC's fair-access policy (`SEC_EDGAR_CONTACT_EMAIL`). FERC
and pipeline-bulletin-board connectors deliberately stay honest `not_configured` stubs — neither
has a single stable public JSON API to build against with confidence, and this sandbox's egress
policy blocks verifying request shapes live against any of these hosts anyway.

**`/` is now a public marketing site; the trading dashboard moved to `/platform`.**
AlphaGasIQ is being extended into a private, admin-provisioned institutional platform — see
`docs/access-model.md`. Milestone 1 lands the frontend groundwork: a public landing page
(`apps/web/app/page.tsx`), a `/login` page with an email-only "Send Secure Magic Link" form
(`POST /auth/magic-link/request` already returns its final non-enumerating generic response,
though real token issuance/email is Milestone 3), and a `/contact` business-inquiry form
(`POST /contact`) that is structurally incapable of creating a user, organization, or session —
there is no `/signup`, `/register`, or `/request-access` route, and none will be added. The
existing dashboard (previously at `/`) now lives at `/platform`, with `chat`/`pipeline-map`/
`model-performance` nested under it (which also fixed a pre-existing bug: those pages weren't
wrapped by the shared header/sidebar layout before). The dev-mode password login stays available
through Milestone 2 so the platform remains usable during the transition.

**Admin-provisioned Users and Organizations are now real, not a placeholder.** Milestone 2 adds
`Organization`/`User`/`Role`/`Permission`/`RolePermission` tables (`packages/db`) and the only
endpoint that can ever create a `User`: `POST /admin/users` (`apps/api/api_app/routers/
admin_users.py`), which looks up or inline-creates the user's organization by company name,
always creates the account `INVITED` (never any other status, no matter what's requested), and
rejects duplicate emails and unrecognized roles. The 8 fixed roles and full permission-key list
seed idempotently on every boot (`SqlAppRepository.seed_rbac_defaults()`); real permission
enforcement lands in Milestone 4, so every `/admin/*` route is gated by today's dev-mode
`ADMIN` role check for now. `apps/api/api_app/account_states.py` implements the account-state
machine (`INVITED`/`ACTIVE`/`SUSPENDED`/`DISABLED`/`EXPIRED`/`LOCKED`/`REVOKED`) enforced by
`POST /admin/users/{id}/status` — `REVOKED` is terminal, and `INVITED`→`ACTIVE` only ever
happens via magic-link activation (Milestone 3), never an admin action. See
`docs/access-model.md`.

**Magic-link authentication, sessions, and the invitation email flow are now real, not
placeholders.** Milestone 3 adds an `EmailProvider` abstraction (`apps/api/api_app/
email_service.py`) defaulting to a console/log-only provider everywhere (real `SMTPEmailProvider`
is config-gated by `SMTP_HOST`, same pattern as OIDC/Neo4j), `MagicLinkTokenRow`/`SessionRow`
(`packages/db`), and a fully real `/auth/magic-link/request` + `GET /auth/magic-link/verify` pair:
a hashed-at-rest, single-use, 15-minute token that activates an `INVITED` user and creates a
revocable `Session`. Session revocation rides a `sid` JWT claim kept deliberately separate from
`sub` (which stays the real `user_id`), so it never disturbs the dev-mode/OIDC login paths, which
carry no `sid` and decode exactly as before. `POST /auth/logout`, `GET /auth/sessions`, and admin
session-listing/revocation endpoints round out spec §20. The dev-mode password login is **kept
permanently** (not removed) as the platform's fixed bootstrap/break-glass credential — see
`docs/access-model.md` §3 for why a "no self-registration, no passwords" platform still needs one.

**RBAC permission checks and feature entitlements are now real, not a role-name placeholder.**
Milestone 4's `apps/api/api_app/entitlements.py` resolves a live effective-permission set for any
authenticated user (dev-mode, OIDC, or magic-link) from the seeded `RolePermission` data, and
`admin_users.py`'s endpoints now require the exact `admin.*` permission the access-model spec
assigns each action (`admin.users.create`, `admin.organizations`, `admin.users.suspend`/
`admin.users.revoke` depending on target status, etc.) instead of a placeholder role check —
verified not to change any existing authorization outcome. `Feature`/`RoleFeatureEntitlement`/
`OrganizationFeatureEntitlement`/`UserFeatureOverride` tables (`packages/db`) seed 18 features
with deny-by-default role grants, allow-by-default org restrictions, and deny-only user overrides
for `security_sensitive` features (Chief Trading Agent Chat, Portfolio/Risk Analytics, Data
Export, API Access, Paper Trading, Experimental Features). `GET /auth/me/entitlements` exposes
both for Milestone 5's dashboard/chat integration to consume next.

**Chief Trading Agent Chat is now permission-gated, and the dashboard enforces entitlements
server-side, not just in the UI.** `POST /chat/sessions/{id}/messages` requires the
`chief_agent.chat` permission; underneath that, `ChatAgent.ask()` checks a per-topic permission
before dispatching to any tool (e.g. a portfolio/scenario question needs `portfolio.view`,
matching spec §28's own worked example) — a declined topic never touches real platform data or
calls the LLM. Chat conversations now persist (`ChatConversationRow`/`ChatMessageRow`) behind the
existing session/message API contract, with admin-only visibility via `GET /chat/conversations`.
`GET /portfolio/*` and `GET /risk/portfolio` now require the `portfolio_analytics`/
`risk_analytics` feature entitlements from Milestone 4 — the two areas the access-model spec
calls out by example, not a full retrofit of every dashboard endpoint. This also caught and fixed
a real bug: a magic-link `SUPER_ADMIN`/`EXECUTIVE`/`API_USER` session was resolving entitlements
from the route-gating role bridge instead of their actual DB role, silently under/mis-granting
permissions — see `docs/access-model.md` §5.

**There's now a real admin console, not just admin-only API endpoints.** Milestone 6 adds
`apps/web/app/platform/admin/*` — Overview (real active/invited/suspended-user and organization
counts, Chief Trading Agent query volume, paper-trading activity, with not-yet-built metrics
honestly marked `null`), Users (create/edit/reassign role or organization/suspend/reactivate/
revoke/resend invitation/send login link), Organizations (create/edit data entitlements), Feature
Management (global/role/organization/user-level toggles across all 18 features, respecting the
deny-override rule for security-sensitive ones), and System Settings (`SUPER_ADMIN`-only,
versioned/reversible via a dedicated history table). Backed by a new `admin_console.py` router
plus `PATCH` endpoints on `admin_users.py` — every action gated by the exact permission the
access-model spec assigns it.

**Data feeds now have a real admin surface, with health and dependency mapping.** Milestone 7
adds `GET/PATCH /admin/data-feeds(/{provider_id})`, `POST .../test-connection`,
`POST .../refresh`, `GET .../events`, and `GET /admin/data-feeds/dependency-map`
(`admin_data_feeds.py`, gated by `admin.data_feeds`). Each feed's admin-editable config
(enabled/paused/polling frequency/freshness threshold/priority/fallback provider/notes) is merged
with its provider's *live* `health_check()` result and a static dependency map built from the real
agent org chart (`docs/agents.md` §2) — no fabricated dependency graph. `DataFeedConfigRow`
deliberately has no credential field: every API key stays environment-provisioned and never
touches the database. Test-connection and manual-refresh actions call the provider's real
`health_check()`/`fetch()` and log the result; a provider failure is recorded as an event, never a
500, since several connectors (FERC, pipeline bulletin boards, licensed news, live CME/ICE) are
intentionally still stubs. `GET /admin/overview`'s data-feed-health fields, `null` since Milestone
6, are now computed from this real data.

**There's now an AI Agent Control Center.** Milestone 8 adds `GET /admin/agents(/{agent_type})`,
`PATCH /admin/agents/{agent_type}`, and `POST /admin/agents/{agent_type}/run`
(`admin_agents.py`, gated by `admin.agent_management`) — an admin-only view of every seat in the
platform's real multi-agent org chart (`agent_catalog.py`, centralizing what `routers/agents.py`'s
org-chart endpoint used to define inline), merged with each implemented agent's live model/version
info, real execution statistics from `agent_execution_log`, and an admin-editable operational
config (status/thresholds/notes, `AgentConfigRow`). The Risk Governor appears for visibility only,
with no admin actions. `POST .../CHIEF_TRADING_AGENT/run` reuses the exact logic behind the
pre-existing manual-trigger endpoint and now refuses to run while paused/disabled; every other
implemented agent is composed internally by the Chief Trading/Investment Agent's own code with no
independent entry point, so running one directly honestly 409s rather than faking a result — and,
stated plainly rather than hidden, pausing such a sub-agent is recorded/visible but doesn't yet
gate its execution inside that composed cycle (see `docs/agent-governance.md` §3).

**Agents now have a real versioning + optimization workflow.** Milestone 9 adds `AgentVersionRow`
(`packages/db`) and `admin_agent_versions.py`: `GET/POST /admin/agents/{agent_type}/versions`,
`GET .../versions/production(/{version_id})`, and `POST .../versions/{version_id}/transition`
(gated by `admin.agent_management`), plus `POST .../optimization/propose` (gated by the stricter,
`SUPER_ADMIN`-only `admin.agent_optimization`). The fixed lifecycle `DRAFT → TESTING → APPROVED →
PRODUCTION → (RETIRED | ROLLED_BACK)` is enforced server-side — no status jump can skip a step, so
no prompt/model change can bypass evaluation. Promoting a version auto-retires the agent's prior
production version; a production agent definition is never overwritten, only ever superseded by a
new row. `optimization/propose` records a real performance-review snapshot from
`agent_execution_log` alongside the admin's stated problem/proposed change, then creates a `DRAFT`
version through that same lifecycle — no optimization-specific fast path to production. Every
implemented agent starts with a real `PRODUCTION` version snapshotted from its actual live
configuration at boot. Stated plainly: nothing yet wires a version's stored config back into how
`services/agents` executes — this is a real, tested governance/versioning system sitting on top of
today's agents, not (yet) a live control surface over their behavior.

**This closes out the access-model spec.** Milestone 10 adds model management (`ModelDefinitionRow`,
`GET/POST /admin/models`, `PATCH /admin/models/{id}/status`, gated by the `SUPER_ADMIN`-only
`admin.model_management`) — an agent version can now only reach `APPROVED`/`PRODUCTION` if its
model is itself an `APPROVED` model definition, enforced structurally in
`transition_agent_version_status`, not by convention. A genuinely append-only `AuditEventRow` and
`audit.py`'s `record_audit_event()` helper (no update/delete path exists, anywhere) back
`GET /admin/audit-logs`, wired into agent status changes, version promotion/rollback, model status
changes, risk-setting changes, and admin user status changes. `GET/PUT /admin/risk-settings`
(`admin.risk_settings`, `SUPER_ADMIN`-only) layers a reason-required, audit-logged surface on top
of the existing `RISK_MANAGER`-facing `/risk/limits` endpoint. `GET /admin/system-health` rolls up
real data-feed/agent/model health, the Risk Governor's status, and event-bus/database connectivity
in one place — the honest data source a fuller pipeline visualization would build on next.

**Milestones 7-10 now have a real admin frontend, not just backend APIs.**
`apps/web/app/platform/admin/{data-feeds,agents,agents/[agentType],models,risk-settings,
audit-log,system-health}` give an administrator a UI for every one of those milestones' endpoints
— data-feed config/test-connection/refresh/ingestion-log, the Agent Control Center (status
toggles, manual Chief Trading Agent run) and per-agent version lifecycle (draft → transition →
promote/rollback, plus the SUPER_ADMIN-only optimization-proposal form), model status management,
reason-required risk-setting changes, the append-only audit log, and the system-health rollup.
`api-client.ts` gained `apiPut`/`apiPatch` helpers (surfacing the API's error `detail` in thrown
errors) alongside the existing `apiGet`/`apiPost`, replacing the raw `fetch()` calls earlier admin
pages had to write inline. Verified end-to-end against the live API and a headless browser (no
console/runtime errors; real data rendering, real state changes, and the expected 403-with-friendly-
message on the two SUPER_ADMIN-only pages when logged in as a plain ADMIN) — not just `next build`.

**Disabling an agent now genuinely stops it from running, and LNG/Power Market are real agents.**
`ChiefTradingAgent.run_research_cycle()` and `InvestmentCommittee.deliberate()` (`services/agents`)
now accept a `disabled_agent_types` set, populated from real `AgentConfigRow` statuses at every
call site (`AppState._run_initial_research_cycle`/`run_chief_trading_cycle`/`_run_quant_research`/
`submit_trade_idea`, plus the standalone `worker.py` cycle) — a disabled agent's `_execute()`
genuinely never runs; `BaseAgent.skipped_result()` records a real `SKIPPED` result in its place
instead. A disabled Investment Committee member forces the decision to `WAIT_FOR_MORE_DATA`
(incomplete quorum, fail closed) rather than silently computing a partial consensus; disabling the
Chief Investment Agent forces the trade to `ApprovalState.REJECTED` rather than defaulting to
approval. Separately, the LNG Agent and Power Market Agent
(`services/agents/agents_service/fundamental/{lng,power_market}.py`) are now real implemented
seats — each wraps its existing deterministic calculation engine
(`fundamentals_service.lng`'s Henry-Hub-to-TTF netback,
`fundamentals_service.power_burn`'s gas-fired power-burn estimate) with one LLM summarization
call, the same pattern every other fundamental agent already uses, and both run every research
cycle alongside the Pipeline Agent with the same admin enable/disable/pause control.

**The pipeline digital twin can now be backed by a real Neo4j instance.**
`fundamentals_service/pipeline_graph_neo4j.py` seeds the same `PipelineGraph`
`build_default_pipeline_graph()` already builds into Neo4j via Cypher `MERGE`, then reloads it —
a real round trip, activated only when `NEO4J_URI` is configured (`docker compose --profile neo4j
up` provisions one). Every default environment keeps the plain in-memory graph, and a sync
failure at boot falls back to it rather than crashing. Same validation posture as the event bus
above: no live Neo4j server is reachable here, so it's tested against faithful `neo4j` driver
test doubles (`tests/fundamentals/test_pipeline_graph_neo4j.py`).

**A new proprietary Alpha Intelligence Layer sits between the digital twin and the Specialized AI
Agents — all six components (AlphaSignal™/AlphaImpact™/AlphaConsensus™/AlphaScenario™/
AlphaMemory™/AlphaReplay™) plus their integration back into the Chief Trading Agent
(AlphaSignal/AlphaConsensus feedback into trade generation, the Overnight Intelligence Brief,
an Overview dashboard) are now implemented, plus the multi-tenant Enterprise Data Platform
(Workspace, six real connector types, fine-grained per-dataset entitlement enforcement, admin
onboarding UI), a tenant-isolation retrofit
(cross-organization data-visibility fix on every Alpha* endpoint, `ModelRoutingPolicy`,
`RetentionPolicy`, `organization_id` schema readiness on core trading tables, now backed by real
Postgres Row Level Security on the same seven call sites) — and the Enterprise Opportunity
Engine + Enterprise-specific Chief Trading Agent chat integration + Enterprise Digital Twin
pipeline overlay.** All 10 milestones of the original roadmap are now implemented; see
`docs/alpha-intelligence.md` section 11.1 for the exact line on what the RLS backstop covers
today versus what still relies on application-layer enforcement alone.
AlphaSignal
(new `services/alpha` package) is a deterministic materiality engine
(`alpha_service.materiality.MaterialityEngine`, in the same pure-function/exhaustively-tested
philosophy as the Risk Governor) plus a signal detector
(`alpha_service.signal_detector.SignalDetector`) that diffs each research cycle's
Supply/Demand/Storage/Weather/LNG/Power/Pipeline agent outputs against the previous cycle's
stored baseline and flags cycle-over-cycle changes that clear a materiality threshold — not
every tick. Exposed via `GET /alpha/signals`/`GET /alpha/signals/{id}` (`alpha_signals.view`
permission), a new "AlphaSignal" chat tool ("What changed overnight?"), and a new
"Alpha Intelligence" dashboard nav section. `organization_id`/`workspace_id` columns exist on
the new `alpha_signals` table from day one (nullable, unenforced) so the schema is
tenant-ready without forcing a premature multi-tenant rearchitecture before this milestone
could ship — real row-level tenant isolation doesn't exist anywhere in this codebase yet
(see `docs/alpha-intelligence.md`'s baseline section for the honest gap analysis) and is a
later milestone in that roadmap, not a Milestone 1 dependency.

**AlphaImpact™ (Milestone 2) explains every signal AlphaSignal detects, chained at the same
integration point.** `alpha_service.impact_engine.ImpactEngine` (also a pure function, no
DB/LLM/event-bus access) builds a causal chain — `EVENT → PHYSICAL → SUPPLY/DEMAND → STORAGE
→ REGIONAL → PRICE/CURVE → STRATEGY → PORTFOLIO → RISK` — from a fixed skeleton selected by
the signal's type, with each stage's confidence/magnitude decaying from the triggering
signal's own confidence/materiality via a documented fixed factor rather than an
independently-modeled per-stage quantity; every `ImpactAnalysis` carries its own
`assumptions`/`uncertainties` saying so explicitly. `AppState._run_alpha_signal_detection()`
runs this immediately after every new signal and publishes `IMPACT_ANALYSIS_CREATED`. Exposed
via `GET /alpha/impacts`/`GET /alpha/impacts/{id}` (`alpha_impacts.view`), a new "Why does it
matter?" chat tool (the natural conversational follow-up to "What changed overnight?"), and a
new sub-nav under "Alpha Intelligence" (AlphaSignal/AlphaImpact tabs, mirroring the admin
console's sub-nav pattern) with an `ImpactsTable` rendering each analysis's causal chain.

**AlphaConsensus™ + Agent Alpha Score™ (Milestone 3) aggregates every contributing agent's
forecast into one dynamically-weighted view.** `alpha_service.forecast_extractor.ForecastExtractor`
(pure) turns each fundamental/quant agent's already-computed output into a common
`AgentForecast` wherever it implies a genuine directional read (never fabricated from a level-
only output like LNG/Power/Pipeline's). `alpha_service.agent_alpha_score.AgentAlphaScoreEngine`
(also pure) rates each agent's reliability — the Forecasting agent gets a real
`BACKTESTED_DIRECTIONAL_ACCURACY` score from the Quant team's walk-forward backtests; every
other agent gets a `CONFIDENCE_CONSISTENCY_PROXY` score, explicitly documented as not a
historical-accuracy claim. `alpha_service.consensus_engine.ConsensusEngine` (also pure) then
weights each forecast by `(alpha_score / 100) * forecast_confidence` — never equal-weighted —
into a `ConsensusView` (bull/bear/neutral probability, agreement label, leading/dissenting
agents), including a specialized storage view that reproduces the flagship "AlphaConsensus vs.
Market Consensus" Bcf comparison. `AppState._run_alpha_consensus()` runs after the quant
research cycle and publishes `AGENT_FORECAST_CREATED`/`CONSENSUS_UPDATED`/
`CONSENSUS_DIVERGENCE_DETECTED`. Exposed via `GET /alpha/consensus`/`GET /alpha/consensus/{market}`
(`alpha_consensus.view`), a new "Do the agents agree?" chat tool (the natural follow-up to "Why
does it matter?"), and a third "AlphaConsensus" tab in the Alpha Intelligence sub-nav.

**AlphaScenario™ (Milestone 4) composes named and/or custom shocks into a richer
counterfactual, then reuses `risk_service/scenarios.py`'s existing P&L/VaR math rather than
duplicating it.** `alpha_service.scenario_engine.ScenarioEngine` (pure) combines named base
scenarios from the standing `risk_service.scenarios.SCENARIOS` catalog with custom
`ScenarioVariable` shocks (price/demand/supply summed, volatility multipliers compounded) into
one composed scenario, then calls the already-tested `run_scenario()` directly — no shadow P&L
math. `run_standing_library()` runs every catalog entry in one pass; `compare()` ranks the
results worst-to-best — the "base vs. A vs. B vs. C" comparison. `AppState.run_alpha_scenario()`/
`run_alpha_scenario_comparison()` persist runs and publish `SCENARIO_RUN`/
`SCENARIO_COMPARISON_RUN`. Exposed via `GET /alpha/scenarios/library`, `POST /alpha/scenarios/run`,
`POST /alpha/scenarios/compare`, `GET /alpha/scenarios/runs`/`GET /alpha/scenarios/runs/{id}`
(new `alpha_scenarios.view`/`alpha_scenarios.run` permissions) — additive to, not a replacement
for, the pre-existing single-scenario `/risk/scenarios` endpoints. The existing scenario chat
topic now composes an explicit percentage shock named in the question ("...and prices spike
20%"); a new "compare scenarios" chat topic runs the whole standing library. A fourth
"AlphaScenario" tab in the Alpha Intelligence sub-nav lets a user run named/composed scenarios,
run the full library, and browse recent run history.

**AlphaMemory™ (Milestone 5) turns every closed trade's already-computed post-trade analysis
into a durable, institutional decision memory plus a human-reviewable lesson proposal.**
`alpha_service.memory_builder.MemoryBuilder` (pure) assembles a `MemoryRecord` from a closed
trade's `TradeIdea`/`InvestmentCommitteeDecision`/`RiskCheckResult`/`PostTradeAnalysis` (and its
attached quant forecast, if any) — carrying forward the existing `OutcomeQuadrant`
classification and lessons string unchanged rather than reclassifying the outcome.
`alpha_service.memory_builder.LessonEngine` (also pure) drafts a lesson from a fixed template
keyed off that outcome quadrant — not an LLM, the same "no LLM in the engine path" discipline as
every other Alpha* engine — always `PENDING` until a human approves or rejects it; nothing here
ever wires an approved lesson back into a production model or threshold automatically.
`AppState._build_decision_memory()` runs immediately after `close_trade()`, persisting via new
`alpha_memory_records`/`alpha_lesson_proposals` tables and publishing `MEMORY_RECORD_CREATED`/
`LESSON_PROPOSED`. Exposed via `GET /alpha/memory`/`GET /alpha/memory/{id}`, `GET /alpha/memory/
lessons`/`GET /alpha/memory/lessons/{id}`, and `POST /alpha/memory/lessons/{id}/review` (new
`alpha_memory.view`/`alpha_memory.review` permissions — the latter narrower, granted only to
RISK_MANAGER/RESEARCHER), a new "what have we learned" chat topic, and a fifth "AlphaMemory" tab
in the Alpha Intelligence sub-nav with an inline Approve/Reject lesson-review panel. Milestone 5
is honest about scope: it links only what is already `trade_id`-linked in this codebase — it
never guesses which `Signal`/`ConsensusView`/`ScenarioRunResult` (if any) informed a given trade,
since no such link exists in the data model today.

**AlphaReplay™ (Milestone 6) reconstructs what the Alpha Intelligence Layer itself knew and
concluded as of a chosen historical moment, bitemporally, so "as known at `<as_of>`" is never
contaminated by a correction that arrived later.** `TimeSeriesObservation`
(`packages/schemas/schemas/observation.py`) gained `revision_time`/`valid_from`/`valid_to`
alongside its existing `observation_time`/`publication_time`, and
`SqlAppRepository.save_market_observation()` closes out a superseded revision's `valid_to`
rather than overwriting it — append-only history, proven correct in
`tests/db/test_market_observations.py` (a revision recorded after `as_of` never leaks into a
query for that `as_of`, even though it's now the current revision). Every other Alpha* list
method gained the same `until`/as-of filtering. `alpha_service.replay_engine.ReplayEngine` (pure)
just packages already-as-of-filtered results; `AppState.compute_as_of_replay()` does the real
work of fetching each series as-of a chosen moment. Milestone 6 is honest about scope: `mode` is
always `CURRENT_MODEL_RETROSPECTIVE` — a replay of what this already-running system itself
recorded at the time, never a reconstruction of market reality from before Milestone 6 shipped,
a replay using the agent versions that existed then, or a full re-simulation of the trade
lifecycle (all three remain future work). Exposed via `GET /alpha/replay` (new
`alpha_replay.view` permission), a new "time machine" chat topic — the first Alpha* topic whose
answer requires an arbitrary-timestamp DB query rather than a bounded in-memory cache, so
`ChatAgent._dispatch()` became `async def` to support it — and a sixth "AlphaReplay" tab in the
Alpha Intelligence sub-nav with an as-of timestamp picker.

**Chief Trading Agent full integration (Milestone 7) closes the loop every Alpha* component
through Milestone 6 left open — each of them ran strictly *after* a `TradeIdea` already existed,
a parallel analysis layer with no feedback path into trade generation.**
`alpha_service.trading_integration.AlphaCorroborationEngine` (pure) cross-checks a freshly-
generated trade against fresh AlphaSignal output and the latest AlphaConsensus view;
`AppState.submit_trade_idea()` — the single choke point every trade idea passes through, in both
research-cycle paths, before the Investment Committee deliberates — merges the result onto the
trade's own `catalysts`/`supporting_data`/`source_citations`/`risks`, so `BullAgent` (reads
`catalysts`) and `SkepticAgent` (reads `source_citations`/`supporting_data`) genuinely see it.
Deliberately conservative: a signal only corroborates or cautions when it clears the materiality
threshold and has a clear directional lean matched against the trade's own direction — a
`SPREAD` trade or a `NEUTRAL` signal is never scored either way. `alpha_service.brief_engine.
BriefEngine` (also pure, template-based, no LLM) composes the Overnight Intelligence Brief — a
cross-component digest of the last 16 hours' signals/impacts/consensus views/scenario runs/
pending lessons, generated once per full research cycle via `AppState.
generate_intelligence_brief()`. Exposed via `GET /alpha/briefs/latest`/`GET /alpha/briefs`/`GET
/alpha/briefs/{id}` (new `alpha_brief.view` permission) and a new "overnight brief" chat topic.
A new root page at `/platform/alpha-intelligence` (`AlphaOverview.tsx`) renders the latest brief
plus six link cards tying the whole layer together; the top-level "Alpha Intelligence" nav link
now points here instead of straight to the AlphaSignal tab, and the sub-nav gained a leading
"Overview" tab. All six Alpha* components and this integration layer are now implemented.

**Enterprise Data Platform foundation (Milestone 8) is a genuine, testable foundation.**
`Workspace`/
`WorkspaceMemberRow` (`packages/db/db/models.py`) group users inside an `Organization`.
`EnterpriseDataSourceRow`/`EnterpriseDatasetRow`/`EnterpriseDataEntitlementRow`/
`EnterpriseRecordRow`/`EnterpriseDataEventRow` back an admin-registered connection to a
customer's proprietary data, its registered datasets, dataset-level access grants
(`principal_type` unifies the plan's `AgentDataEntitlement` into the same table rather than a
structurally-identical parallel one), ingested rows, and a test-connection/ingest event log.
The new `services/enterprise_data` package's `BaseEnterpriseDataConnector`
(`test_connection`/`discover_schema`/`preview`/`ingest`/`health_check`) mirrors `data_sdk.
provider.BaseDataProvider`'s shape; all six `EnterpriseConnectorType` values are implemented
end-to-end (`ManualUploadConnector`/`WebhookConnector` take rows from the request body / an
HMAC-verified inbound-push staging buffer; `RestApiConnector`/`DatabaseConnector`/`S3Connector`/
`SftpConnector` pull live via `httpx`/`sqlalchemy`/`boto3`/`paramiko` from wherever the source's
non-secret `connection_config` points), the same "must work with zero paid subscriptions"
discipline every `Mock*Provider` already establishes — a connector missing its required
configuration or environment-provisioned credential honestly reports `not_configured` rather
than pretending to work. `EnterpriseDataSourceRow` deliberately carries no credential field,
mirroring `DataFeedConfigRow`'s existing posture; every connector resolves its actual secret
from an environment variable named (never stored) in `connection_config`. Exposed via
`/admin/workspaces(/{id}/members)` and `/admin/enterprise-data/sources(/{id}/
test-connection|/datasets)`/`/admin/enterprise-data/datasets/{id}(/preview|/ingest|/records|
/entitlements)` plus the public, signature-verified `POST /webhooks/enterprise-data/{source_id}`
ingress (new `admin.workspaces`/`admin.enterprise_data` permissions), and new "Workspaces" and
"Enterprise Data" admin console tabs.

**Tenant isolation retrofit (Milestone 9) closes the two cross-organization data-visibility
gaps Milestone 8's own write-up flagged, and adds the governance layer it deferred — now backed
by real Postgres Row Level Security (`packages/db/db/rls.py`) on the same seven call sites, not
just the application layer.**
`resolve_organization_scope(user, state) -> (organization_id, unrestricted)`
(`apps/api/api_app/entitlements.py`) replaces `resolve_organization_id` at every `/alpha/*`
read call site: previously a caller whose own organization couldn't be resolved got *every*
organization's rows on a list endpoint (the filter was simply skipped), and a get-by-id
endpoint performed no organization check at all. Every affected `Repository.list_*` method
gained a `platform_only: bool` parameter (restricting a non-admin, no-resolvable-org caller to
`organization_id IS NULL` rows), and `record_is_visible(record_org, caller_org, unrestricted)`
gates every get-by-id endpoint, 404ing on an invisible record rather than 403ing (never
confirming a record's existence to an unauthorized caller).
`tests/api/test_alpha_tenant_isolation.py` proves the fix end-to-end. Those same seven
`list_*` methods, and the matching seven get-by-id methods (`get_signal`,
`get_impact_analysis`, etc. — a gap-closure follow-up), now also set the Postgres session
variable `app.current_org_id` (`Repository._set_org_guc`) with the exact same
`organization_id`/`platform_only` precedence, and every organization-scoped table has `FORCE
ROW LEVEL SECURITY` plus a permissive-by-default `org_isolation` policy
(`packages/db/db/rls.py`) — a real database-level backstop, not a
replacement for the application-layer filter. `tests/db/test_rls.py`'s live-Postgres suite
proves RLS restricts even a raw query with no `.where()` filter at all; against SQLite (every
default dev/test database) it's a documented no-op. New `ModelRoutingPolicy`/
`RetentionPolicy` tables (`packages/schemas/schemas/enterprise.py`) govern, per
`(organization_id, EnterpriseDataClassification)`, whether content may reach an external LLM
provider and how long data may be retained — `ModelRoutingEngine`/`RetentionEngine`
(`services/enterprise_data/enterprise_data_service/`) resolve policy purely (organization
override winning over a platform default), `PolicyGatedLLMProvider`
(`packages/agent-sdk/agent_sdk/llm.py`) and `AppState.apply_retention_policy()` are the real
enforcement primitives — both `ModelRoutingEngine` and `PolicyGatedLLMProvider` now have a
real live caller: `ChatAgent._enterprise_data_query` (below: the Enterprise-specific Chief
Trading Agent chat tool) evaluates `ModelRoutingEngine` per dataset to decide what content
reaches the facts handed to the LLM, and separately wraps the final prose-synthesis call in a
`PolicyGatedLLMProvider` gated by the combined decision across every involved dataset, so a
blocked classification also keeps that summarization step off an external LLM entirely.
Exposed via `/admin/model-routing-policies`/
`/admin/retention-policies(/apply)` (new `admin.model_routing_policy`/`admin.retention_policy`
permissions) — API-only, no admin UI yet. Finally, `trade_ideas`/`committee_decisions`/
`risk_checks`/`approvals` each gained a nullable `organization_id` column that now round-trips
from `TradeIdea.organization_id` through `AppState.submit_trade_idea()` — schema readiness
only, since every trade idea today still comes from the single process-wide `AppState`'s
system-generated research cycle, never a per-organization submission path.

**Milestone 10 (Enterprise Opportunity Engine + Enterprise-specific Chief Trading Agent chat
integration + Enterprise Digital Twin pipeline overlay) completes the original 10-milestone
Alpha Intelligence Layer roadmap.** `EnterpriseOpportunity`
(`packages/schemas/schemas/enterprise.py`, `organization_id` **required**, not nullable — an
opportunity is inherently one organization's own, unlike every other Alpha*/enterprise table)
is a human-reviewed candidate opportunity `EnterpriseOpportunityEngine`
(`services/enterprise_data/enterprise_data_service/opportunity.py`, pure, zero I/O) drafts by
cross-referencing an organization's own `POSITION`/`PORTFOLIO`-domain enterprise records
against recent `Signal`s/`ConsensusView`s — `HEDGE_MISALIGNED_POSITION` (a held position runs
counter to a high-confidence consensus view) or `NEW_POSITION_HIGH_CONVICTION_SIGNAL` (a
high-materiality directional signal with no existing position); never auto-executed, the same
"AI-drafted but always human-reviewed" posture `LessonProposal` already establishes.
`AppState.generate_enterprise_opportunities()` does the I/O; `GET/POST
/alpha/enterprise/opportunities*` (`enterprise_opportunities.view`/`.generate`/`.review`) is
the API, tenant-isolated via the same `resolve_organization_scope`/`record_is_visible`
Milestone 9 helpers; a new "Opportunities" dashboard tab lists/generates/reviews. A new chat
topic, `ChatAgent._enterprise_data_query` (gated by new `enterprise_data.query`), is the
Enterprise-specific Chief Trading Agent: answers using the caller's own organization's
registered enterprise datasets, and is the first real caller `ModelRoutingEngine` has had —
each dataset's resolved `ModelRoutingPolicy` decision gates whether its content is described
or withheld, never silently included in the facts handed to the LLM. `GET
/alpha/enterprise/pipeline-overlay` is the Enterprise Digital Twin overlay: the public
pipeline graph plus the caller's own organization's `ASSET`/`FACILITY`-domain enterprise
records pinned onto real nodes in it (`PipelineOverlayPoint.from_record`/`build_overlay`, pure)
— the pipeline map page gained a "Show my enterprise assets" toggle. A follow-up pass wired the
Enterprise-specific Chief Trading Agent into actual trade generation:
`AppState.generate_enterprise_trade_idea(organization_id=...)` runs the same
fundamentals-\>strategy pipeline `run_chief_trading_cycle()` runs, tags the resulting trade with
`organization_id`, and submits it through the normal `submit_trade_idea()` path, which now also
runs `EnterpriseCorroborationEngine`
(`services/enterprise_data/enterprise_data_service/trading_integration.py`, pure, mirrors
`AlphaCorroborationEngine`) — a same-market position in the organization's own book becomes
supporting data, an opposing one becomes a risk, both reaching `BullAgent`/`SkepticAgent` in
committee deliberation. A new chat topic, `ChatAgent._enterprise_trade_idea` (gated by new
`enterprise_trading.generate`, TRADER only), triggers it. Both the data-query chat tool and
the pipeline overlay are now also narrowed by fine-grained per-dataset
`EnterpriseDataEntitlement` grants (`filter_entitled_enterprise_datasets`,
`apps/api/api_app/entitlements.py`) — a dataset with no entitlement rows stays visible to the
whole organization, but once at least one grant exists only a matching principal sees it.
`AppState._load_enterprise_positions()`'s org-wide aggregate read path (opportunity/trade
generation) now also enforces entitlements, via new `agent_is_entitled()`
(`enterprise_data_service.dataset_entitlement`) -- this pipeline has no per-caller *human*
principal, so it presents a fixed `AppState.ENTERPRISE_POSITION_READER_AGENT_TYPE` identity
against a dataset's `AGENT`-type grants (a dataset's USER/ROLE/WORKSPACE grants, for human
dashboard/chat visibility, don't affect this separate check). `AppState.
generate_enterprise_opportunities_for_all_organizations()` gives opportunity generation a real
scheduled cadence -- `worker.py`'s existing periodic loop calls it every interval alongside the
Chief Trading Agent's own research cycle, on top of the still-available on-demand
`POST /alpha/enterprise/opportunities/generate`. `AppState.
apply_retention_policies_for_all_organizations()` gives retention purging the same real
scheduled cadence, in its own loop iteration. Real database-level Row Level Security (see the
tenant-isolation section above) covers the same seven Alpha* `list_*` and get-by-id call sites
the application-layer fix does, plus schema-level readiness on 14 more organization-scoped
tables including `enterprise_opportunities` itself -- extending the GUC-setting to this
pipeline's own read/write paths remains future work.

**Observability**: every request now emits a structured JSON log line (timestamp, level,
logger, method, path, status code, latency, a generated request id echoed back as the
`X-Request-ID` response header) via `RequestLoggingMiddleware`/`JsonFormatter`
(`apps/api/api_app/logging_config.py`), shared by both the API process and `worker.py` in
place of the old bare `logging.basicConfig`. Exception tracking via Sentry
(`sentry_sdk.init(...)`, `FastApiIntegration`/`StarletteIntegration`) is config-gated by
`SENTRY_DSN`, same honest-no-op pattern as `SMTP_HOST`/`OIDC_ISSUER_URL`/`NEO4J_URI` -- unset in
every default dev/test environment, so `sentry-sdk` is imported and initialized only when a
real DSN is configured. `SENTRY_TRACES_SAMPLE_RATE` (default `0.0`) and `LOG_LEVEL` (default
`INFO`) are also configurable.

**Live updates**: dashboard pages previously only fetched once on mount. `GET /ws/events`
(`apps/api/api_app/routers/ws.py`) now streams dashboard-relevant events (new signals, trade
approvals/rejections, risk breaches, opportunities, intelligence briefs, consensus divergence)
to the browser over a WebSocket, filtered to the caller's own organization the same way every
REST endpoint already is. `apps/web/lib/live-events-context.tsx`'s `LiveEventsProvider` owns one
shared connection per session (mounted in `apps/web/app/platform/layout.tsx`), with
auto-reconnect and a small status indicator; `SignalsTable.tsx` is wired as the worked
example -- a new signal appears without a manual refresh. Other dashboard tables follow the same
`useLiveEvents().subscribe(...)` pattern as a small follow-up, not applied everywhere in this
pass.

**Phase 1 free data feed integration** (docs/data-sources.md): every EIA/NOAA connector existed
but was never actually called by the running application outside an admin-triggered manual
refresh -- `AppState._seed_market_and_fundamentals()` populated the fundamentals engine entirely
from synthetic seed generators, and `worker.py` hardcoded a fake `weather_kwargs` dict that
falsely claimed "GFS"/"ECMWF" without ever calling either. `AppState.
refresh_fundamentals_from_public_data()` (called at boot and on every worker cycle) closes this
for the two fields whose real source data is granular enough to use honestly: `storage_baseline`
from EIA's real weekly storage history (once `EIA_API_KEY` is configured) and `weather_kwargs`
from NOAA's real national HDD/CDD (NOAA needs no key, so this always updates). `self.balances`
(the daily natural-gas balance engine) deliberately stays synthetic -- EIA publishes fundamentals
weekly/monthly, never daily, and interpolating a fake daily shape from monthly totals would be
estimation presented as real precision it doesn't have. The EIA connector grew from 2 series to
8 (Henry Hub futures front-month, consumption by sector, LNG exports), NOAA gained severe-weather
alerts and a national HDD/CDD approximation, a new deterministic `DataQualityService`
(0-100 score: missing/impossible values, timestamp sanity, a jump check) populates
`ObservationDraft.quality_score` for the first time, and a `compute_freshness_status()` state
machine (`LIVE`/`CURRENT`/`DELAYED`/`STALE`/`FAILED`/`UNKNOWN`) replaces "the API call succeeded"
as proof of currency in the admin Data Feeds panel. `DataSourceBadge`/`FreshnessTag` (previously
only wired into `StoragePanel.tsx`) now also label `ForwardCurveChart.tsx` (showing "Real-Time
NYMEX Data Not Enabled" when the forward curve is simulated), `MarketIntelGrid.tsx`, and
`WeatherPanel.tsx` -- real vs. simulated data is never shown unlabeled. `ObservationDraft`/
`TimeSeriesObservation` also gained licensing metadata (`license_type`, `redistribution_allowed`,
`ai_processing_allowed`), populated conservatively (EIA/NOAA are public-domain U.S. government
data) rather than left to default permissive.

**Phase 1 free data feed integration, round 2** (docs/data-sources.md §6-8): a new
`TropicalWeatherConnector` (`providers/nhc.py`) covers NOAA's National Hurricane Center
`CurrentStorms.json` feed, no API key required, flagging a coarse Gulf-of-Mexico proximity
heuristic distinct from any confirmed-impact claim. The EIA connector gained an LNG imports
series (9th, for symmetry with exports) and `ISORTOProvider` gained an actual electricity-demand
route alongside its existing generation-by-fuel route. A new `compute_market_bias()`
(`services/alpha/alpha_service/market_bias.py`) replaces the platform's ad-hoc, misleadingly-named
`ai_market_bias` field (a raw LONG/SHORT trade-idea count on `/market/summary` that was never
actually AI-decided) with a real, deterministic, weighted score built from up to eight
independently-computed drivers (weather, storage, production, demand, LNG, power, price momentum,
agent consensus) -- each driver returns `None`, never a fabricated contribution, when its inputs
are missing, and the whole result is `INSUFFICIENT_DATA` if every driver is. Exposed at
`GET /alpha/market-bias` (full breakdown) and summarized on `/market/summary` and a new
`MarketBiasCard` dashboard panel.

**Upgrade version panel**: the admin Upgrade page (`/platform/admin/upgrade`) previously
offered a button and a log, with no way to tell what the deployment was actually running.
`apps/api/api_app/version.py` + `GET /admin/upgrade/version` now report three deliberately
separate facts, because conflating them caused a real incident (a dependency fix appeared to
be deployed for days while the running image never contained it). **Current** is the commit the
*image* was built from — stamped into `/app/build-info.json` by a throwaway `gitstamp` stage in
`Dockerfile.api`, so it answers "what code is executing", not "what has the host checked out".
**Remote** is the newest commit on the tracked branch, from the GitHub API
(`repos/{repo}/commits/{branch}`), cached 60s so polling the page cannot exhaust the anonymous
rate limit. **Host checkout** is optional (the upgrade agent writes
`/deploy/checkout-info.json`) and exists only to raise `rebuild_required` when the working tree
is ahead of the running image — the pull-without-rebuild case. Between Current and Remote,
`compare/{base}...{head}` lists the incoming commits and the Upgrade button names its target
("Upgrade to `98aff9a`"), matching the ElavoFishAI version card. Every lookup degrades to
`unknown`/`error` rather than raising: an unstamped dev run (`uvicorn --reload`) and an
unreachable GitHub both still render. The panel names the branch it compares against, because
the failure mode it cannot otherwise catch is a fix pushed to a *different* branch than the one
this host pulls — no rebuild will ever bring that in. `UPGRADE_REPO`/`UPGRADE_BRANCH`/
`GITHUB_TOKEN` are configurable from the Configuration page ("Upgrade" group); the repo is
public today, so the token is only a rate-limit lever.
