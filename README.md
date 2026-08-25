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
            -e services/data -e services/fundamentals -e services/risk \
            -e services/paper-execution -e services/agents -e apps/api
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

## Repository layout

See `docs/architecture.md` §6. Short version: `/apps` (web, api) · `/services` (data, agents,
fundamentals, risk, paper-execution, ...) · `/packages` (schemas, agent-sdk, data-sdk, ui,
config) · `/infrastructure` (Docker, DB migrations) · `/docs` · `/tests`.

## Current implementation status

This repo implements Milestones 1-9 of the phased build plan in `docs/architecture.md` §8 at
MVP depth: repo/db/auth/dashboard shell, EIA/NOAA/mock-market/mock-news ingestion, the natural
gas balance + storage forecast + weather-demand engines, the Chief Trading Agent with
Supply/Demand/Storage/Weather agents, a Directional Strategy Agent, the AI Investment
Committee (Bull/Bear/Skeptic/Data Integrity/Portfolio), the deterministic Risk Governor, the
paper-trading engine, and the AI Trader Chat. Milestones 10 (full pipeline digital twin /
interactive map — a minimal illustrative graph ships now) and 11 (post-trade learning) are
intentionally left as the next increment, per "build sequentially, don't build everything at
once." The MVP persistence layer is in-memory (`apps/api/api_app/state.py`), seeded at
startup; `infrastructure/db/migrations` defines the production Postgres/TimescaleDB schema it
mirrors, and swapping in a SQLAlchemy-backed repository is the next milestone's wiring — no
router changes required.

Known follow-ups: the pinned `next` version has open advisories addressed only by a Next 16
major upgrade (deferred to avoid an unreviewed breaking change); production auth should
replace the dev-mode JWT issuer with a real OIDC provider.
