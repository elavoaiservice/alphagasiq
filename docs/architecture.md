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

In the MVP (Milestones 1-2), the event bus is implemented behind an `EventBus` interface
(`packages/agent-sdk/eventbus.py`) with an in-process/Redis pub-sub implementation so the stack
boots with `docker compose up` without requiring a full Kafka cluster; a Redpanda-backed
implementation is provided and becomes the default once `EVENT_BUS_IMPL=redpanda` is set. This
keeps local dev cheap while preserving the production interface.

## 5. Technology Stack

| Layer | Choice |
|---|---|
| Backend services | Python 3.11+, FastAPI, Pydantic v2 |
| Database | PostgreSQL 16 + TimescaleDB extension |
| Cache / pub-sub | Redis 7 |
| Streaming | Kafka-compatible (Redpanda for dev), abstracted `EventBus` |
| Orchestration | Temporal (durable workflows), abstracted behind `WorkflowEngine` for MVP |
| Frontend | Next.js 14 (App Router), React 18, TypeScript, Tailwind CSS |
| Charting | TradingView Lightweight Charts; Mapbox/deck.gl for the pipeline map |
| AI | Anthropic Claude via `packages/agent-sdk/llm.py` `LLMProvider` interface |
| ML | scikit-learn, XGBoost, LightGBM, statsmodels, PyTorch (interfaces only initially) |
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
`LiveBrokerExecutionAdapter`, Neo4j-backed pipeline graph, Kafka-backed `EventBus`) rather than
building them speculatively ahead of need.

Milestones 10 and 11 are now implemented at MVP depth alongside 1-9:

- **Milestone 10 (pipeline digital twin)**: `services/fundamentals/fundamentals_service/pipeline_graph.py`
  models ~30 nodes across every node type (production basins, processing plants,
  interconnects, storage, city gates, power plants, LNG terminals, Mexico export points, hubs)
  and ~27 edges across every edge type, with capacity/scheduled-flow/actual-flow/utilization/
  maintenance/constraint/basis-relationship fields. A `PipelineAgent` (Fundamental Research
  Team) surfaces constrained corridors and active maintenance. The frontend map
  (`apps/web/components/pipeline-map/PipelineMap.tsx`) is a dependency-free inline-SVG network
  view — no Mapbox token required — click a node to open `PipelineNodeInspector`.
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
  `ForecastModel` interface with two real implementations (naive persistence, OLS linear trend)
  and an honest `NotImplementedModel` stub for every other model type the brief names (ARIMA,
  VAR, state-space, Random Forest, XGBoost, LightGBM, TFT, LSTM — `GET /quant/models` reports
  which are real), a metrics module (MAE, RMSE, directional accuracy, hit rate, profit factor,
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
