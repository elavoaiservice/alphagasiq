# Alpha Intelligence Layer — AlphaSignal™, AlphaImpact™, AlphaConsensus™, AlphaScenario™,
# AlphaReplay™, AlphaMemory™, and the Enterprise Data Platform

This document covers the full target architecture for AlphaGasIQ's proprietary Alpha
Intelligence Layer — six interconnected components that sit between the Natural Gas Digital
Twin and the Specialized AI Agents — plus the multi-tenant Enterprise Data Platform that lets
authorized energy-company customers combine their own proprietary data with this layer. It is
a large, multi-milestone initiative (larger in scope than the access-model build documented in
`docs/access-model.md`/`docs/agent-governance.md`), delivered the same way: one milestone at a
time, each planned, built, tested, documented, and committed before the next begins.

**Status as of this document**: Milestones 1 (AlphaSignal™) and 2 (AlphaImpact™) are
implemented. Milestones 3-10 below are architecture + roadmap only — not yet built. Do not
assume any capability described here beyond the "Implemented" sections actually exists in the
codebase yet.

## 1. Where this sits in the pipeline

The platform's architecture evolves from:

```
DATA → AI AGENTS → TRADING DECISIONS
```

into:

```
DATA
  ↓
NATURAL GAS DIGITAL TWIN                    (services/data, services/fundamentals — existing)
  ↓
ALPHA INTELLIGENCE LAYER                    (this document)
  AlphaSignal™ · AlphaImpact™ · AlphaConsensus™ · AlphaScenario™ · AlphaReplay™ · AlphaMemory™
  ↓
SPECIALIZED AI AGENTS                       (services/agents — existing)
  ↓
AI INVESTMENT COMMITTEE                     (services/agents/agents_service/committee — existing)
  ↓
CHIEF TRADING AGENT                         (existing)
  ↓
INDEPENDENT RISK GOVERNOR                   (services/risk — existing, absolute veto, unchanged)
  ↓
HUMAN TRADER / PORTFOLIO
```

The Alpha Intelligence Layer converts raw information into structured market intelligence
*before* downstream agents make recommendations — it does not replace the Investment
Committee, the Chief Trading Agent, or the Risk Governor, and it never gains any authority
they don't already have. In particular, **nothing in this layer can reach or influence the
Risk Governor's rule chain** — the same non-negotiable boundary `docs/agent-governance.md §1`
already establishes for every other agent.

## 2. Baseline: what's reusable vs. genuinely new

Before building any of this, the existing codebase was audited so later milestones don't
duplicate what's already there or silently assume infrastructure that doesn't exist.

**Reusable as-is:**

- `Organization`/`Role`/`Permission`/`Feature` tables + the 3-tier entitlement resolution
  (global → role → org → user-override) in `apps/api/api_app/entitlements.py`
  (`require_permission`, `require_feature`, `get_effective_permissions`). Every new endpoint
  and chat tool in this layer plugs into this exactly, never the older `require_role`.
- The event bus (`packages/schemas/schemas/events.py`'s `EventType`/`DomainEvent`,
  `packages/agent-sdk/agent_sdk/eventbus.py`'s `EventBus`/`InMemoryEventBus`/
  `RedpandaEventBus`) — new event types are added to `EventType`, published from inside
  `AppState` mutator methods right after the durable write, exactly like every existing
  `TRADE_IDEA_CREATED`/`RISK_LIMIT_BREACHED`/etc. call site.
- The chat tool pattern (`apps/api/api_app/chat_agent.py`): no formal "Tool" class — a
  keyword router (`_route`) into a `_dispatch()` if/elif chain, each topic permission-checked
  via a static `_TOOL_PERMISSIONS` dict *before* dispatch. Every `Alpha*Tool` in section 12 is
  a new topic in this same router, not a new abstraction.
- `BaseDataProvider`/`ProviderRegistry` (`packages/data-sdk/data_sdk/provider.py`) is the
  direct analog for the future `BaseEnterpriseDataConnector` (section 8).
- The deterministic, pure-function, exhaustively-tested design of
  `risk_service.governor.RiskGovernor` is the model for every scoring/rules engine in this
  layer (AlphaSignal's materiality engine, and later AlphaConsensus's weighting) — no LLM
  ever sits in a scoring path itself.
- `services/risk/risk_service/scenarios.py`'s `Scenario`/`run_scenario` is the direct
  precedent AlphaScenario (section 6) extends, not replaces.

**Genuinely new — no existing scaffolding:**

- **Multi-tenant row-level isolation.** No business-data table (trade ideas, committee
  decisions, risk checks, agent results) is scoped by `organization_id` today, and there is a
  single process-wide `AppState` singleton (`apps/api/api_app/state.py`, module-level
  `_state`). The `Organization`/`Role`/`Permission`/`Feature` tables govern *feature
  visibility and admin RBAC*, not *row-level data segregation* — every organization's users
  see the same shared dataset today. Real tenant isolation (Postgres RLS or equivalent,
  `organization_id`/`workspace_id` enforcement in the repository layer) is new
  infrastructure, sequenced as Milestone 9 below rather than a prerequisite to shipping the
  six Alpha components against today's shared dataset.
- **Workspace** as an entity between `Organization` and `User` does not exist anywhere yet.
- The existing `DataClassification` enum (`PUBLIC`/`LICENSED`/`USER_PROVIDED`/`SIMULATED`,
  `packages/schemas/schemas/enums.py`) is a **data-provenance** tag on ingested observations
  — it is not the enterprise **security-tier** classification section 7 describes
  (`CUSTOMER_CONFIDENTIAL`, `CUSTOMER_RESTRICTED`, etc.). The enterprise concept needs its own
  name (proposed: `EnterpriseDataClassification`) to avoid colliding with the existing one.
- `BaseEnterpriseDataConnector`, secrets management, connector onboarding UI, agent/model data
  entitlements, model routing policy, retention policy — all new (sections 7-10).

Every new Alpha* table gets a nullable `organization_id`/`workspace_id` column from day one
(NULL = a platform-wide record, the only kind any milestone through Milestone 8 produces) so
the schema is tenant-ready without forcing a premature `AppState` rearchitecture before value
can ship.

## 3. Roadmap

| # | Component | Status |
|---|---|---|
| 1 | AlphaSignal™ — material-change detection + materiality engine | **Implemented** |
| 2 | AlphaImpact™ — event→market causal chain | **Implemented** |
| 3 | AlphaConsensus™ + Agent Alpha Score™ — calibrated, dynamically-weighted consensus | **Implemented** |
| 4 | AlphaScenario™ — counterfactual/stress-test engine | Planned |
| 5 | AlphaMemory™ — decision/institutional memory | Planned |
| 6 | AlphaReplay™ — bitemporal historical reconstruction | Planned |
| 7 | Chief Trading Agent full integration — all six `Alpha*Tool`s, Morning Brief, Overview dashboard | Planned |
| 8 | Enterprise Data Platform foundation — Workspace, connectors, admin onboarding UI | Planned |
| 9 | Tenant isolation retrofit — real `organization_id`/`workspace_id` enforcement, model routing policy, retention policy | Planned |
| 10 | Enterprise-specific Chief Trading Agent + Enterprise Digital Twin overlays + Opportunity Engine | Planned |

AlphaImpact through AlphaReplay (2-6) are sequenced before the Enterprise Data Platform (7-10)
deliberately: they deliver real value against today's shared public/simulated dataset first,
and the harder structural work of true multi-tenant isolation and proprietary connectors comes
after there are six working components for enterprise data to plug into. AlphaReplay is last
among the six because it is the most invasive — it retrofits bitemporal columns onto existing
observation tables — so it's sequenced after the other five have real data worth replaying.

## 4. AlphaSignal™ (implemented)

**Purpose**: detect *material* changes in the natural gas ecosystem — not every tick, only
the ones that clear a deterministic materiality bar. Feeds every other Alpha component:
AlphaImpact explains a signal, AlphaConsensus aggregates forecasts around it, AlphaScenario
stress-tests it, AlphaMemory remembers it.

**Schema** (`packages/schemas/schemas/alpha.py`): `Signal` — `id`, `organization_id`,
`workspace_id`, `signal_type` (`SignalType`: `PRICE_MOVE`, `CURVE_CHANGE`,
`VOLATILITY_CHANGE`, `PRODUCTION_CHANGE`, `DEMAND_CHANGE`, `STORAGE_CHANGE`,
`WEATHER_CHANGE`, `PIPELINE_CONSTRAINT`, `PIPELINE_OUTAGE`, `LNG_CHANGE`, `POWER_CHANGE`,
`NEWS_EVENT`, `REGULATORY_EVENT`, `POSITION_CHANGE`, `PORTFOLIO_CHANGE`,
`RISK_LIMIT_APPROACH`, `CUSTOMER_DATA_CHANGE`, `MODEL_DISAGREEMENT`, `AGENT_DISAGREEMENT`,
`ANOMALY`), `category`, `subcategory`, `source_ids`, `detected_at`, `effective_at`, `market`,
`geography`, `asset_ids`, `headline`, `description`, `previous_value`, `current_value`,
`absolute_change`, `percent_change`, `z_score`, `historical_percentile`,
`materiality_score` (0-100), `novelty_score` (0-100, always `0.0` in Milestone 1 — a real
recurrence-based heuristic is deferred), `confidence`, `direction` (`SignalDirection`:
`BULLISH`/`BEARISH`/`NEUTRAL` — a new enum, distinct from `Direction`'s LONG/SHORT/SPREAD
trade posture), `time_horizon`, `data_quality` (reuses `DataClassification`), `citations`
(reuses `Citation`), `affected_agents`, `affected_business_functions`, `status`
(`SignalStatus`: `ACTIVE`/`ACKNOWLEDGED`/`ESCALATED`/`EXPIRED` — Milestone 1 always leaves a
signal `ACTIVE`; the other three states are for a future acknowledgement workflow).

**Materiality engine** (`services/alpha/alpha_service/materiality.py`): `MaterialityEngine`,
a deterministic, non-LLM rules engine in the same design philosophy as `RiskGovernor` — pure
function of its input, exhaustively unit-tested (`tests/alpha/test_materiality.py`). Combines
four weighted, 0-100-normalized components:

- **Magnitude** (weight 0.4) — `|percent_change|` scaled against a saturation point (a 20%
  change or larger scores 100); missing `percent_change` scores 50 (medium, not zero — "no
  data" must not look identical to "no change").
- **Rarity** (weight 0.3) — `|z_score|` scaled against a saturation point (a z of 4 or larger
  scores 100), falling back to distance-from-median `historical_percentile` if no z-score is
  available; missing both scores 0 (unremarkable, not overstated).
- **Confidence** (weight 0.2) — the contributing agent's own `AgentResult.confidence`,
  scaled to 0-100.
- **Data quality** (weight 0.1) — a fixed lookup by `DataClassification`
  (`LICENSED`=100, `PUBLIC`=80, `USER_PROVIDED`=70, `SIMULATED`=60), halved if the reading
  is stale.

These weights and the default pass threshold (60.0, `DEFAULT_MATERIALITY_THRESHOLD`) are a
**provisional, documented business judgment call** — tunable once real signal volume exists
to calibrate against, not derived from data yet. A per-`SignalType` threshold override map can
be supplied to `MaterialityEngine.__init__` for later tuning without changing the scoring
logic itself.

**Signal detector** (`services/alpha/alpha_service/signal_detector.py`): `SignalDetector`,
also pure — no DB or event-bus access happens inside it. `detect()` takes the current research
cycle's already-computed fundamental-agent outputs (Supply/Demand/Storage/Weather/LNG/Power/
Pipeline `AgentResult`s) plus the previous cycle's stored per-metric baseline
(`BaselineSnapshot`: last value + a bounded rolling window used for the z-score), and returns
any `Signal`s that cleared the materiality threshold plus updated baselines. Milestone 1
detects: `PRICE_MOVE` (front-month market curve price), `STORAGE_CHANGE` (forecast vs. prior
cycle and vs. market consensus), `WEATHER_CHANGE` (total demand delta), `PRODUCTION_CHANGE`,
`DEMAND_CHANGE`, `LNG_CHANGE`, `POWER_CHANGE`, `PIPELINE_CONSTRAINT`, and a simplified
`AGENT_DISAGREEMENT` check (a deterministic directional-lean comparison across Storage/
Weather/Supply/Demand — explicitly *not* a true multi-model consensus/weighting engine; that
is AlphaConsensus, section 5). Every other `SignalType` value exists on the schema for
forward-compatibility but is not yet produced by this detector.

**Integration** (`apps/api/api_app/state.py`): `AppState._run_alpha_signal_detection()` owns
all the I/O the pure detector doesn't — loads `SignalBaselineRow`s via
`SqlAppRepository.get_signal_baselines()`, calls `SignalDetector.detect()`, saves updated
baselines and any new `SignalRow`s, publishes `SIGNAL_DETECTED` (or `SIGNAL_ESCALATED` when
`materiality_score >= 85`) `DomainEvent`s, and appends to a bounded in-memory
`AppState.recent_signals` cache (last 50) so the (synchronous) chat-tool dispatch methods in
`chat_agent.py` can read the latest signals the same way every other tool method reads
`AppState`, without making that one dispatch path async-aware. Called from both
`_run_initial_research_cycle()` (boot) and `run_chief_trading_cycle()` (on-demand) — the
latter doesn't re-run LNG/power/pipeline, so those three arguments are `None` on that path and
the detector simply skips the rules that need them.

**API** (`apps/api/api_app/routers/alpha.py`): `GET /alpha/signals` (filterable by `market`,
`since_hours`, `min_materiality`, `limit`; ranked highest-materiality-first, then most recent;
gated by the `alpha_signals.view` permission) and `GET /alpha/signals/{signal_id}`. When the
requester resolves to a real organization, results include both that organization's own
signals and every platform-wide signal (`organization_id IS NULL`) — the only kind this
milestone's detector produces — rather than hiding the global feed from every tenant.

**Entitlements** (`packages/db/db/repository.py`): permission `alpha_signals.view` (granted
to `TRADER`/`RISK_MANAGER`/`RESEARCHER`/`EXECUTIVE`/`VIEWER` by default, mirroring
`trading_recommendations.view`'s grant pattern, plus `SUPER_ADMIN`/`ADMIN` automatically) and
feature `alpha_intelligence` (granted alongside `ai_trade_recommendations` — which `VIEWER`
does not have, so `VIEWER` gets the API permission but not the dashboard feature flag,
intentionally: the permission gates data access, the feature gates the UI section).

**Chat tool**: `AlphaSignalTool` — a new `"what_changed_overnight"` topic in
`chat_agent.py`, routed from "overnight"/"material change"/"alphasignal" phrasing (kept
distinct from the pre-existing `"what_changed"` topic, which reads the raw agent execution
log rather than ranked signals), permission `alpha_signals.view`, reads
`state.recent_signals` and returns the top 5 by materiality.

**Dashboard**: a new "Alpha Intelligence" nav entry under `/platform` links to
`/platform/alpha-intelligence/signals` (`apps/web/app/platform/alpha-intelligence/signals/
page.tsx` + `apps/web/components/alpha-intelligence/SignalsTable.tsx`), a client component
using the same `useAuth()`-token + `apiGet` pattern as the admin data-feeds page, rendering a
materiality-ranked table.

## 5. AlphaImpact™ (implemented)

**Purpose**: takes a `Signal` AlphaSignal already detected and determines what it *means* —
the causal chain from physical event to portfolio implication:

```
EVENT → PHYSICAL IMPACT → SUPPLY/DEMAND IMPACT → STORAGE IMPACT → REGIONAL IMPACT →
PRICE/CURVE IMPACT → STRATEGY IMPACT → PORTFOLIO IMPACT → RISK IMPACT
```

**Schema** (`packages/schemas/schemas/alpha.py`): `ImpactCategory` (the eight stages above),
`ImpactEdge` (one causal link — `sequence_index`, `category`, `from_node`, `to_node`,
`description`, `confidence`, `magnitude`, `supporting_evidence` — so the frontend renders the
chain as a graph with per-link confidence, not a single opaque verdict) and `ImpactAnalysis`
(`signal_id`, `organization_id`, `event_type`, `physical_impact`, `supply_impact_bcf_day`,
`demand_impact_bcf_day`, `storage_impact_bcf`, `expected_duration`, `affected_geographies`/
`assets`/`markets`/`contracts`, `basis_implications`, `curve_implications`,
`volatility_implications`, `portfolio_implications`, `risk_implications`, `bullish_bearish`,
`magnitude`, `confidence`, `assumptions`, `uncertainties`, `alternative_interpretations`,
`data_sources`, `agent_contributors`, `chain: list[ImpactEdge]`).

**Impact engine** (`services/alpha/alpha_service/impact_engine.py`): `ImpactEngine.analyze()`
is pure — no DB/event-bus/LLM access — exactly like `MaterialityEngine`/`SignalDetector`. A
fixed skeleton of `ImpactCategory` stages is selected by the signal's `SignalType` (the full
8-stage fundamentals skeleton for Supply/Demand/Storage/Weather/LNG/Power/Pipeline signals; a
4-stage market skeleton — `PRICE_CURVE → STRATEGY → PORTFOLIO → RISK` — for
PRICE_MOVE/CURVE_CHANGE/VOLATILITY_CHANGE; a 3-stage `STRATEGY → PORTFOLIO → RISK` skeleton
for AGENT_DISAGREEMENT/MODEL_DISAGREEMENT; a 2-stage `PORTFOLIO → RISK` skeleton for signal
types that are already portfolio-level events). Each stage's `confidence`/`magnitude` decay
multiplicatively from the triggering signal's own `confidence`/`materiality_score` via a fixed
per-stage factor (0.92) — later stages are never more confident than earlier ones, reflecting
compounding uncertainty. Milestone 2 is deliberately honest about scope: **this is not an
independently-modeled per-stage quantitative forecast** — every `ImpactAnalysis` carries its
own `assumptions`/`uncertainties` saying so explicitly, rather than silently implying more
precision than actually exists. The one genuinely computed number per analysis is the direct
fundamental mapping where it's unambiguous — `PRODUCTION_CHANGE`/`PIPELINE_CONSTRAINT`/
`PIPELINE_OUTAGE` → `supply_impact_bcf_day`; `DEMAND_CHANGE`/`WEATHER_CHANGE`/`POWER_CHANGE`/
`LNG_CHANGE` → `demand_impact_bcf_day`; `STORAGE_CHANGE` → `storage_impact_bcf` — each simply
carried forward from the signal's own `absolute_change` where the mapping is direct, not
independently recomputed. `bullish_bearish`/`magnitude`/`confidence` are likewise carried
forward from the triggering signal's own `direction`/`materiality_score`/`confidence` — an
independently-modeled *impact* magnitude, distinct from the triggering signal's materiality,
is future work.

**Integration** (`apps/api/api_app/state.py`): `AppState._run_alpha_signal_detection()` runs
`ImpactEngine.analyze()` against every newly-persisted `Signal` in the same loop, immediately
after saving the signal and publishing its `SIGNAL_DETECTED`/`SIGNAL_ESCALATED` event —
signal detection and impact analysis are chained at one integration point, not two separate
call sites. Persists via `ImpactAnalysisRow` (chain stored as an embedded JSON column, since
it's always fetched with its parent and never queried edge-by-edge independently), publishes
`IMPACT_ANALYSIS_CREATED` (with `lineage_ids=[signal_id]`), and appends to a bounded in-memory
`AppState.recent_impacts` cache alongside `recent_signals`.

**API**: `GET /alpha/impacts` (filterable by `signal_id`, `since_hours`, `limit`; gated by a
new `alpha_impacts.view` permission, granted to the same role set as `alpha_signals.view`) and
`GET /alpha/impacts/{impact_id}`.

**Chat tool**: `AlphaImpactTool` — a new `"why_does_it_matter"` topic ("Why does it matter?"/
"why is that important"), permission `alpha_impacts.view`, matches `state.recent_impacts` to
the highest-materiality entry in `state.recent_signals` by `signal_id` and narrates the causal
chain — the natural conversational follow-up to AlphaSignal's "What changed overnight?".

**Dashboard**: the "Alpha Intelligence" nav section now has its own sub-nav
(`apps/web/app/platform/alpha-intelligence/layout.tsx`, mirroring the admin console's
sub-nav pattern) with AlphaSignal and AlphaImpact tabs — `/platform/alpha-intelligence/impacts`
(`ImpactsTable.tsx`) lists recent impact analyses and renders the selected one's causal chain
as an ordered list with per-stage confidence/magnitude.

**Enterprise personalization** (section 8's `ImpactAnalysis` "customer-specific view"
alongside the general market view) remains planned, not built — `affected_contracts` is
always empty and no enterprise-data branch exists yet, since the Enterprise Data Platform
milestones (7-10) haven't been built.

## 6. AlphaConsensus™ + Agent Alpha Score™ (implemented)

**Purpose**: an internal prediction/opinion aggregation system. Specialized agents
independently submit an `AgentForecast` (forecast value, direction, probability, confidence,
time horizon, evidence). **Agent Alpha Score™** rates each predictive agent's reliability.
`AlphaConsensus` then computes a *dynamically weighted* (never equal-weighted) consensus view
using each agent's current Alpha Score and its own forecast confidence as the weight — the
same "no LLM in the scoring path, deterministic and testable" philosophy as the Risk Governor,
AlphaSignal's materiality engine, and AlphaImpact's causal-chain builder.

**Schema** (`packages/schemas/schemas/alpha.py`): `AgentForecast` (`agent_id`, `agent_type`,
`agent_version`, `organization_id`, `forecast_type`, `target`, `market`, `horizon`,
`forecast_value`, `direction`, `probability`, `confidence`, `drivers`, `citations`);
`AgentAlphaScore` (`agent_type`, `score` 0-100, `method`, `sample_size`, `components`);
`ConsensusWeight` (`agent_type`, `weight`, `alpha_score`, `forecast_confidence`, `direction`);
`ConsensusView` (`consensus_type`, `market`, `target`, `horizon`, `consensus_value`,
`bull_probability`/`bear_probability`/`neutral_probability`, `confidence`, `dispersion`,
`agreement_label`, `agent_count`, `agent_weights: list[ConsensusWeight]`, `leading_agents`,
`dissenting_agents`, `drivers`, `risks`, `market_consensus_value`, `variance_vs_market`).

**Forecast extraction** (`services/alpha/alpha_service/forecast_extractor.py`):
`ForecastExtractor.extract()` is pure — no DB/LLM/event-bus access — and turns each
fundamental/quant agent's already-computed `AgentResult.outputs` into the common
`AgentForecast` shape. It only extracts a forecast where the source agent's own single-cycle
output already implies a genuine directional read: Storage (tighter-than-consensus is
bullish), Weather (`price_direction` already computed by the agent), Supply (rising
production is bearish), Demand (rising demand is bullish), Forecasting (the Quant team's
`PriceForecast.up_probability`), and Relative Value (`CHEAP`/`RICH`). LNG/Power/Pipeline
agents are deliberately excluded — their single-cycle output reports a current *level*, not a
*trend*, so extracting a direction from it would be fabricated, unlike AlphaSignal's detector,
which can infer a trend from its own cycle-over-cycle baseline diff.

**Agent Alpha Score™** (`services/alpha/alpha_service/agent_alpha_score.py`):
`AgentAlphaScoreEngine.score()` is honest about scope — only the Forecasting agent has a
genuine historical-accuracy figure available today, `METHOD_BACKTESTED` (each contributing
model's real walk-forward `BacktestResult.directional_accuracy`, weighted by
`PriceForecast.model_contributions`). Every other agent gets `METHOD_CONFIDENCE_PROXY` — a
weighted blend of mean recent confidence, confidence consistency (low variance scores higher),
and evidence quality (citation coverage) — explicitly **not** a claim of historical predictive
accuracy, since no resolved-outcome ledger per fundamental agent exists yet (building one
requires linking each forecast to what actually happened later, which is AlphaMemory's
decision-memory infrastructure, a later milestone). Weights (0.5/0.3/0.2) are provisional,
like AlphaSignal's materiality weights.

**Consensus engine** (`services/alpha/alpha_service/consensus_engine.py`):
`ConsensusEngine.compute()` weights each forecast by `(alpha_score / 100) * forecast_confidence`
— never equal-weighted — normalizes to sum to 1.0 (falling back to equal weighting only if
every contributor has zero effective weight), and aggregates into bull/bear/neutral
probability shares, an `agreement_label` (HIGH/MEDIUM/LOW by the majority direction's share),
and leading/dissenting agent lists. A single scalar `consensus_value` is only computed when
every contributing forecast shares the exact same `target` (e.g. all `STORAGE_BCF`) — averaging
a price forecast with a production-trend forecast would be meaningless. Returns `None` for an
empty forecast list rather than a misleadingly "no conviction" zeroed-out view.

**Integration** (`apps/api/api_app/state.py`): `AppState._run_alpha_consensus()` runs after
the quant research cycle, extracting forecasts from that cycle's Storage/Weather/Supply/
Demand/Forecasting/Relative-Value `AgentResult`s, recomputing each contributing agent type's
`AgentAlphaScore`, and computing two `ConsensusView`s: a general `MARKET_DIRECTION` view across
all contributing agents, and (when a Storage forecast is present) a specialized
`STORAGE_FORECAST` view that reproduces the flagship "AlphaConsensus vs. Market Consensus"
comparison from the platform-forecast Bcf figure against the external EIA-survey consensus
figure. Fixed a latent data-flow gap in the process: the Storage Agent's own raw
`AgentResult.outputs` never carries `market_consensus_bcf` — that figure was only ever merged
in downstream, ephemerally, when `chief_trading_agent.py` builds the Directional Strategy
Agent's `StorageForecast` input. `market_consensus_bcf` is now threaded explicitly from
`_run_initial_research_cycle` through to the forecast extractor so this comparison isn't
silently unavailable. Persists via `AgentForecastRow`/`AgentAlphaScoreRow` (natural-key,
upserted per `agent_type`)/`ConsensusViewRow`, publishes `AGENT_FORECAST_CREATED` per forecast
and `CONSENSUS_UPDATED` (or `CONSENSUS_DIVERGENCE_DETECTED` when `agreement_label == "LOW"`)
per view, and appends to a bounded in-memory `AppState.recent_consensus_views` cache alongside
`recent_signals`/`recent_impacts`.

**API**: `GET /alpha/consensus` (filterable by `consensus_type`, `since_hours`, `limit`; gated
by a new `alpha_consensus.view` permission granted to the same role set as
`alpha_signals.view`/`alpha_impacts.view`), `GET /alpha/consensus/{market}` (latest view for a
market — the flagship comparison endpoint), and `GET /alpha/consensus/by-id/{consensus_id}`.

**Chat tool**: `AlphaConsensusTool` — a new `"agent_consensus"` topic ("Do the agents agree?"/
"what does AlphaConsensus say"/"agent alpha score"), permission `alpha_consensus.view`, reads
`state.recent_consensus_views` and narrates the bull/bear/neutral split, the AlphaConsensus
value vs. market consensus where available, and leading/dissenting agents — the natural
conversational follow-up to AlphaImpact's "Why does it matter?". Routed carefully so
"disagree" (the pre-existing `most_disagreeing_agent` topic) is never shadowed by the new
"agree" keyword.

**Dashboard**: a third "AlphaConsensus" tab in the Alpha Intelligence sub-nav —
`/platform/alpha-intelligence/consensus` (`ConsensusTable.tsx`) lists recent consensus views
and renders the selected one's bull/bear/neutral probability bar, AlphaConsensus-vs-market
comparison, and per-agent weight/Alpha-Score/direction table.

**Enterprise personalization** (a workspace's own model routing/preferences influencing
consensus weighting) remains planned, not built — every `ConsensusView` produced today is
platform-wide (`organization_id IS NULL`), since the Enterprise Data Platform milestones
(7-10) haven't been built.

## 7. AlphaScenario™ (planned)

Extends `risk_service/scenarios.py`'s existing `Scenario`/`run_scenario` (currently a static
14-scenario catalog with a single price/demand/supply/volatility shock per scenario) into a
richer counterfactual engine: `Scenario`/`ScenarioVariable` (multi-factor shocks with
geography/asset/duration) / `ScenarioResult` (supply/demand/storage/price/curve/basis/
volatility/portfolio changes), natural-language-to-scenario parsing in the Chief Trading Agent
("What happens if ECMWF removes 20 HDDs and Freeport loses 1 Bcf/d for two weeks?"), scenario
comparison (base vs. A vs. B vs. C), and a continuously-maintained library of standard stress
tests (polar vortex, hurricane, major LNG/pipeline outage, TTF spike/collapse, etc. — largely
already named in `risk_service.scenarios.SCENARIOS`, extended with richer shock composition).
Enterprise customers will be able to build private stress scenarios using their own portfolio/
asset data once section 8's platform exists.

## 8. AlphaMemory™ (planned)

Machine institutional memory: preserves the full history of signals, impact analyses,
consensus views, scenarios, trade ideas, committee/CTA/risk/human decisions, outcomes, and
lessons. Core entity: `MemoryRecord` (typed by `MemoryType`: `MARKET_MEMORY`, `EVENT_MEMORY`,
`AGENT_MEMORY`, `STRATEGY_MEMORY`, `PORTFOLIO_MEMORY`, `DECISION_MEMORY`,
`HUMAN_FEEDBACK_MEMORY`, `ERROR_MEMORY`, `MODEL_MEMORY`, `ORGANIZATION_PRIVATE_MEMORY`), each
carrying structured context, linked source records, and a similarity embedding. **Decision
Memory** is the centerpiece: for every material recommendation, a complete record of what was
known → what AlphaSignal/AlphaImpact/AlphaConsensus concluded → what scenarios were run → what
agents disagreed → what the Committee/CTA/Risk Governor/human each decided → what happened →
whether the thesis was correct, classified into one of the four decision-vs-outcome quadrants
`OutcomeQuadrant` already defines (reused from the existing post-trade-analysis schema —
`docs/architecture.md`'s "Milestone 11" work already established that a profitable outcome and
a good decision are not the same thing; AlphaMemory extends that discipline to every material
signal, not just closed trades). Lesson proposals are AI-drafted but always human-reviewed
before they can influence any production model or threshold — never an automatic feedback
loop. Memory scoping (global AlphaGasIQ memory vs. organization vs. workspace vs. user) follows
directly from section 9's tenant model once it exists; until then, all memory is platform-wide
by construction, exactly like Milestone 1's signals.

## 9. AlphaReplay™ (planned)

Historical market-state reconstruction under one hard rule: **only use information that was
available at the selected historical moment** — no look-ahead bias, no data revisions from the
future, no future news or model output contamination. Requires strengthening the bitemporal
concept already implicit in `ObservationDraft`/`TimeSeriesObservation`
(`observation_time`/`publication_time`, `packages/schemas/schemas/observation.py`) into a full
bitemporal model (adding `received_time`, `revision_time`, `valid_from`/`valid_to`) across
every observation table, so a query can ask "as known at <timestamp>". Four replay modes:
historical reality, current-model replay (today's agents against historical information),
original-model replay (the agent/model versions that actually existed then, using
`AgentVersionRow`'s versioning from `docs/agent-governance.md §4`), and full strategy replay.
The planned "Market Time Machine" UI steps chronologically through a historical period (e.g.
"replay Winter Storm Uri") with agents reacting only as information would have arrived. This
is sequenced last among the six components because it is the most invasive schema change and
benefits from having real decision history (AlphaMemory) to validate against.

## 10. Enterprise Data Platform (planned, Milestones 7-10 above)

### 10.1 Multi-tenant architecture

New concepts, layered on top of the existing `Organization`/`Role`/`Permission`/`Feature`
tables rather than replacing them: `Workspace` (new — a grouping inside an `Organization`),
`DataSource`, `Dataset`, `DataEntitlement`, `AgentEntitlement`/`AgentDataEntitlement` (which
agents may read which datasets — e.g. a Weather Agent has no portfolio access, a Portfolio
Agent has position access only if entitled; the Chief Trading Agent only ever gets access
through the requesting user's own authorization context, never a standing grant),
`ModelEntitlement`, `Portfolio`. Every proprietary data object carries `organization_id`,
`workspace_id` (where applicable), a security-tier classification (proposed name
`EnterpriseDataClassification` — see section 2 on why it can't reuse the existing
`DataClassification` enum), `owner`, `source`, `permissions`, `lineage`, `retention_policy`,
`created_at`/`updated_at`. Tenant isolation is enforced server-side and at the database/
service layer — never solely by frontend filtering — using PostgreSQL Row Level Security or
equivalent where practical; every service call carries verified tenant context.

### 10.2 Security-tier data classification

`PUBLIC`, `LICENSED_MARKET_DATA`, `ALPHAGASIQ_PROPRIETARY`, `CUSTOMER_CONFIDENTIAL`,
`CUSTOMER_RESTRICTED`, `CUSTOMER_POSITION_DATA`, `CUSTOMER_RISK_DATA`, `SIMULATED`. Access
rules combine organization, workspace, role, permission, this classification, feature
entitlement, dataset entitlement, and agent entitlement.

### 10.3 Enterprise data connectors

`BaseEnterpriseDataConnector` (methods: `connect()`, `test_connection()`, `authenticate()`,
`discover_schema()`, `preview()`, `ingest()`, `incremental_sync()`, `validate()`,
`normalize()`, `health_check()`, `disconnect()`) — the same abstraction shape as today's
`BaseDataProvider`, generalized to proprietary connector types (REST/GraphQL/SFTP/secure file
upload/CSV/Excel/JSON/Parquet, Postgres/SQL Server/Snowflake/Databricks read replicas, S3/
Azure Blob/GCS, Kafka, webhooks, customer-defined adapters) rather than hardcoded per-vendor
integrations. Example customer data domains: production/well/basin data, pipeline capacity
and transportation rights, storage contracts/inventory, LNG positions and cargo schedules,
power generation/fuel requirements, physical/financial contracts and hedges, internal
research/forecasts, risk limits, operational outages and nominations.

### 10.4 Admin onboarding, canonical model, and safeguards

An Admin "Enterprise Data" section (Sources/Datasets/Mappings/Permissions/Health/Lineage/
Usage/Dependencies tabs) lets an administrator add a source, configure connection details,
store secrets through a proper secrets-management abstraction (raw secret values are never
redisplayed after entry — the same posture today's data-feed admin page already takes, where
credentials are environment-provisioned only with no credential field in the UI at all), test
the connection, discover schema, map fields/units/timezone, set classification/refresh/
freshness/retention, assign workspace/agent/user access, and run manual syncs. All external
and proprietary data normalizes into the same canonical energy data model domains
(`MARKET_PRICE`, `PRODUCTION`, `DEMAND`, `WEATHER`, `STORAGE`, `PIPELINE`, `TRANSPORTATION`,
`LNG`, `POWER`, `NEWS_EVENT`, `POSITION`, `PORTFOLIO`, `HEDGE`, `CONTRACT`, `RISK`,
`FORECAST`, `SCENARIO`, `ASSET`, `FACILITY`, `NODE`, `FLOW`) with the same rich metadata
(source, organization, dataset, observation/publication/received time, unit, geography,
confidence, revision, quality score, lineage, permissions) `ObservationDraft` already
establishes for market data. A `ModelRoutingPolicy` (organization + data classification →
allowed LLM provider/models/region/logging/retention) gates the existing `LLMProvider`
abstraction (`packages/agent-sdk/agent_sdk/llm.py`) so `CUSTOMER_RESTRICTED` data can be
routed only through approved/private model infrastructure when
`ALLOW_EXTERNAL_LLM_PROCESSING=False` for that organization — never silently sent to a public
model API. Data loss prevention extends to logs, monitoring payloads, and cross-organization
vector search (AlphaMemory's similarity search must never let one customer's confidential data
improve another customer's outputs without explicit contractual authorization).

## 11. Transparency and explainability

Every major output from every component above must let an authorized human see: what data was
used and when it was received, which agents/models contributed, what assumptions were made,
what disagreed, what uncertainty exists, what historical analogues were used, and — when
enterprise data influenced the result — which datasets, without ever exposing raw sensitive
values unless the requester is authorized. This mirrors the existing
`apps/api/api_app/explainability.py` contract (`what`/`why`/`why_now`/`catalyst`/`confidence`/
`risk`/`sources`) that every trade idea already carries — the Alpha Intelligence Layer extends
that same discipline upstream of the trade idea, not a new philosophy. **Never exposed**:
private chain-of-thought. **Always exposed**: evidence, decision rationale, structured causal
chains, assumptions, uncertainty, sources, and agent contributions.
