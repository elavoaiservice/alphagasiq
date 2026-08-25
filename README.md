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

This repo implements all 11 milestones of the phased build plan in `docs/architecture.md` §8
at MVP depth:

- **1-4**: repo/db/auth/dashboard shell, EIA/NOAA/mock-market/mock-news ingestion, the natural
  gas balance + storage forecast + weather-demand engines, the Chief Trading Agent with
  Supply/Demand/Storage/Weather/Pipeline agents.
- **5 (quantitative platform)**: `services/quant` — a point-in-time-correctness module
  (`pit.py`, guarding against the exact EIA-style reporting-lag look-ahead bug the brief calls
  "critical"), two real forecasting models (naive persistence, OLS linear trend) plus an honest
  `NotImplementedModel` stub for every other model type named (ARIMA/VAR/state-space/Random
  Forest/XGBoost/LightGBM/TFT/LSTM — `GET /quant/models` shows which), the metrics module (MAE,
  RMSE, directional accuracy, hit rate, profit factor, Sharpe, Sortino, max drawdown, Brier
  score), a multi-horizon forecast engine, a deterministic regime-detection engine, a
  relative-value engine (HH-TTF netback + calendar spread), and a walk-forward backtesting
  engine — all wrapped by four Quantitative Team agents (Forecasting/Regime
  Detection/Relative Value/Backtesting) and exposed via `/quant/*`.
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

The MVP persistence layer is in-memory (`apps/api/api_app/state.py`), seeded at startup;
`infrastructure/db/migrations` defines the production Postgres/TimescaleDB schema it mirrors,
and swapping in a SQLAlchemy-backed repository remains the next-increment wiring — no router
changes required.

Known follow-ups: the pinned `next` version has open advisories addressed only by a Next 16
major upgrade (deferred to avoid an unreviewed breaking change); production auth should
replace the dev-mode JWT issuer with a real OIDC provider.
