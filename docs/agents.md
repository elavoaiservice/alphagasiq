# Agent Architecture

AlphaGasIQ is built as a **multi-agent trading organization**, not one monolithic agent. Every
agent is a small, testable unit implementing `packages/agent-sdk`'s `BaseAgent`, with a single
responsibility and an explicit, typed I/O contract.

## 1. Mandatory Agent Contract

Every agent execution — regardless of team — produces an `AgentResult`
(`packages/schemas/agent.py`) exposing exactly these fields:

```
agent_id                # stable identifier, e.g. "fundamentals.supply.v1"
agent_name              # human-readable, e.g. "Supply Agent"
agent_type              # enum: which team/role
version                 # semver of the agent's logic/prompt
status                  # SUCCESS | PARTIAL | FAILED | SKIPPED
inputs                  # typed summary of inputs consumed (ids, not full payloads)
outputs                 # typed result payload
tools                   # tool names invoked during this run
data_sources            # source ids/series consulted, each with classification
confidence              # 0-1
last_execution_time     # timestamp
execution_duration      # ms
reasoning_summary       # concise rationale: evidence, assumptions, model outputs, citations
citations               # list of {source, url_or_id, publication_time}
errors                  # list of structured errors, empty on success
```

**No agent ever exposes private chain-of-thought.** `reasoning_summary` is a distilled, auditable
rationale — evidence considered, assumptions made, model outputs used, and citations — generated
deliberately for the record, not a raw model transcript. Every `AgentResult` is persisted to
`agent_executions` (append-only) so every conclusion the platform reaches is traceable.

## 2. Organization Chart

```
CHIEF TRADING AGENT
├── FUNDAMENTAL RESEARCH TEAM
│   ├── Supply Agent            – Lower-48 production, Canadian imports, other supply
│   ├── Demand Agent             – res/comm, industrial, Mexico exports, other demand
│   ├── Storage Agent            – EIA storage nowcast/forecast, 5yr avg/range, EOS projection
│   ├── Weather Agent            – HDD/CDD, model-run deltas, WeatherDemandImpact
│   ├── LNG Agent                 – feedgas, terminal utilization, netback economics
│   ├── Pipeline Agent            – flows, constraints, outages, digital-twin state
│   └── Power Market Agent        – ISO/RTO load & generation mix, power burn estimate
├── MARKET INTELLIGENCE TEAM
│   ├── Market Data Agent         – curve construction, continuous contracts, basis
│   ├── News Intelligence Agent   – ingest → classify → structured NewsEvent
│   ├── Event Detection Agent     – cross-references news + ops data for confirmed events
│   └── Sentiment Agent           – aggregate directional tone across sources
├── QUANTITATIVE TEAM
│   ├── Forecasting Agent         – multi-horizon price/return forecasts
│   ├── Regime Detection Agent    – classifies current market regime
│   ├── Relative Value Agent      – cross-contract/cross-market mispricing signals
│   └── Backtesting Agent         – walk-forward validation of models & strategies
├── STRATEGY TEAM                 – each strategy agent emits TradeIdea objects only
│   ├── Directional Strategy Agent
│   ├── Calendar Spread Agent
│   ├── Basis Strategy Agent
│   ├── Storage Arbitrage Agent
│   ├── LNG Arbitrage Agent
│   ├── Volatility Strategy Agent
│   └── Event Strategy Agent
├── AI INVESTMENT COMMITTEE       – debates every material TradeIdea
│   ├── Bull Agent
│   ├── Bear Agent
│   ├── Skeptic Agent
│   ├── Data Integrity Agent
│   └── Portfolio Agent
├── INDEPENDENT RISK ORGANIZATION – organizationally and technically separate service
│   ├── Market Risk Agent
│   ├── Portfolio Risk Agent
│   ├── Liquidity Risk Agent
│   ├── Data Risk Agent
│   ├── Model Risk Agent
│   └── Risk Governor             – deterministic, non-LLM, absolute veto (see risk-framework.md)
└── CHIEF INVESTMENT AGENT        – receives research + proposed trades; CANNOT override
                                     the Risk Governor
```

The **Chief Trading Agent** orchestrates the research → strategy → committee pipeline for a
given instrument/theme and hands the resulting (already committee-reviewed) trade ideas to the
**Chief Investment Agent**, whose only remaining authority is to forward, hold, or kill a trade
idea for human review — subject unconditionally to the Risk Governor's verdict.

## 3. Tooling Model

Agents do not call the LLM freely; they call it through `packages/agent-sdk/llm.py`'s
`LLMProvider` (Claude by default) with a **tool-use loop** restricted to the specific tools that
agent is allowed: data-provider queries, the balance/storage/weather engines, the quant model
registry, and (for the AI Trader Chat agent) read-only platform query tools. This is what
prevents hallucinated market facts — every numeric claim an agent makes must come from a tool
call result that is logged as a `citation`.

## 4. MVP Implementation Scope

Implemented so far: the Chief Trading Agent and Chief Investment Agent; Supply, Demand,
Storage, Weather, and Pipeline agents (Fundamental Research Team); News Intelligence Agent
(Market Intelligence Team); the full Quantitative Team — Forecasting, Regime Detection,
Relative Value, and Backtesting agents (`services/agents/agents_service/quant/`, backed by
`services/quant`); the Directional Strategy Agent; and the full AI Investment Committee
(Bull/Bear/Skeptic/Data Integrity/Portfolio).

Every `AgentType` enum member is defined whether or not a concrete agent exists for it yet.
Unbuilt seats (Market Data, Event Detection, Sentiment, the remaining Strategy Team members,
the Independent Risk Org's non-Governor agents) are simply not instantiated — there is no
`NotImplementedAgent` class; instead `GET /agents` reports each `AgentType`'s
`implemented` flag from a maintained roster (`apps/api/api_app/routers/agents.py`), so the
org chart is always introspectable via the API even before every seat is filled. This mirrors
the honesty pattern used for unbuilt data connectors (`NotImplementedProvider`) and unbuilt
quant models (`NotImplementedModel`) — never claim a seat is filled when it isn't.
