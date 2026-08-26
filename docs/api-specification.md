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
| POST | `/auth/login` | dev-mode credential login, returns JWT (kept for local development only through Milestone 2; removed once Milestone 3 wires real magic-link issuance — see `docs/access-model.md`) |
| POST | `/auth/magic-link/request` | `{email}` — **always** returns the same generic `{"message": "If an authorized AlphaGasIQ account exists for this email, a secure sign-in link has been sent."}` regardless of whether the email matches a user, to prevent account enumeration. No token issuance or email dispatch yet (Milestone 1 placeholder; real behavior lands in Milestone 3) |
| GET | `/auth/me` | current user + roles |
| GET | `/auth/mode` | `{"oidc_configured": bool}` — whether real SSO is available on this deployment |
| GET | `/auth/oidc/login` | redirects to the configured IdP's authorization endpoint (PKCE); `501` if OIDC isn't configured |
| GET | `/auth/oidc/callback` | IdP redirect target; validates the ID token (JWKS signature, issuer, audience, nonce), maps claims to a `Role` set, and redirects to the frontend (`/platform#access_token=...`) with this platform's own session JWT in the URL fragment |

## Contact (public, no account creation)

| Method | Path | Notes |
|---|---|---|
| POST | `/contact` | Public business-inquiry form submission (first/last name, business email, company, job title, phone, inquiry type, message). Persists a `ContactInquiry` row for admin visibility only. **Never** creates a `User`, `Organization`, `MagicLinkToken`, or session — see `docs/access-model.md` "No Self-Registration." |

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
| GET | `/risk/portfolio` | current exposure/greeks/VaR/ES/drawdown |
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
| GET | `/portfolio/positions` | current paper positions |
| GET | `/portfolio/pnl` | daily/realized/unrealized P&L |
| GET | `/paper-orders` | simulated order/fill history |

## Decision Journal / Post-Trade

| Method | Path | Notes |
|---|---|---|
| GET | `/journal/{trade_id}` | full decision journal entry |
| GET | `/post-trade/{trade_id}` | post-trade analysis once closed |
| GET | `/models/performance` | Milestone 11 model-performance dashboard: win rate, avg thesis/timing/risk accuracy, decision-vs-outcome quadrant counts, and per-strategy breakdown over every closed trade; plus a `quant` section comparing each `services/quant` model's walk-forward-backtested directional accuracy to its live directional accuracy/Brier score from closed trades that had a forecast attached |

## AI Trader Chat

| Method | Path | Notes |
|---|---|---|
| POST | `/chat/sessions` | create a chat session |
| POST | `/chat/sessions/{id}/messages` | send a message; returns assistant reply with citations |
| GET | `/chat/sessions/{id}` | full transcript |
| WS | `/ws/chat/{id}` | streaming token delivery |

All list endpoints support `limit`/`cursor` pagination. All responses embed
`data_sources`/`citations`/`freshness` metadata wherever the payload includes market or research
facts, per the platform's explainability requirement.
