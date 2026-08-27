# Alpha Intelligence Layer — AlphaSignal™, AlphaImpact™, AlphaConsensus™, AlphaScenario™,
# AlphaReplay™, AlphaMemory™, and the Enterprise Data Platform

This document covers the full target architecture for AlphaGasIQ's proprietary Alpha
Intelligence Layer — six interconnected components that sit between the Natural Gas Digital
Twin and the Specialized AI Agents — plus the multi-tenant Enterprise Data Platform that lets
authorized energy-company customers combine their own proprietary data with this layer. It is
a large, multi-milestone initiative (larger in scope than the access-model build documented in
`docs/access-model.md`/`docs/agent-governance.md`), delivered the same way: one milestone at a
time, each planned, built, tested, documented, and committed before the next begins.

**Status as of this document**: Milestones 1-7 (AlphaSignal™, AlphaImpact™, AlphaConsensus™ +
Agent Alpha Score™, AlphaScenario™, AlphaMemory™, AlphaReplay™, and Chief Trading Agent full
integration) are implemented. Milestone 8 (Enterprise Data Platform foundation — `Workspace`,
`EnterpriseDataSource`/`EnterpriseDataset`/`EnterpriseDataEntitlement`, one real connector) is
implemented as a foundation only — see section 11 for exactly what that does and does not
include. Milestones 9-10 below (tenant isolation retrofit, enterprise-specific Chief Trading
Agent overlays) are architecture + roadmap only — not yet built. Do not assume any capability
described here beyond the "Implemented" sections actually exists in the codebase yet.

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
  via a static `_TOOL_PERMISSIONS` dict *before* dispatch. Every `Alpha*Tool` (one per component,
  documented alongside that component's own section below) is a new topic in this same router,
  not a new abstraction.
- `BaseDataProvider`/`ProviderRegistry` (`packages/data-sdk/data_sdk/provider.py`) is the
  direct analog for the future `BaseEnterpriseDataConnector` (section 11.3).
- The deterministic, pure-function, exhaustively-tested design of
  `risk_service.governor.RiskGovernor` is the model for every scoring/rules engine in this
  layer (AlphaSignal's materiality engine, and later AlphaConsensus's weighting) — no LLM
  ever sits in a scoring path itself.
- `services/risk/risk_service/scenarios.py`'s `Scenario`/`run_scenario` is the direct
  precedent AlphaScenario (section 7) extends, not replaces.

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
- **Workspace** as an entity between `Organization` and `User` did not exist anywhere at the
  time this section was written; Milestone 8 (section 11) has since added it.
- The existing `DataClassification` enum (`PUBLIC`/`LICENSED`/`USER_PROVIDED`/`SIMULATED`,
  `packages/schemas/schemas/enums.py`) is a **data-provenance** tag on ingested observations
  — it is not the enterprise **security-tier** classification section 11.2 describes
  (`CUSTOMER_CONFIDENTIAL`, `CUSTOMER_RESTRICTED`, etc.). The enterprise concept needs its own
  name (proposed: `EnterpriseDataClassification`) to avoid colliding with the existing one.
- `BaseEnterpriseDataConnector`, secrets management, connector onboarding UI, agent/model data
  entitlements, model routing policy, retention policy — all new (section 11).

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
| 4 | AlphaScenario™ — counterfactual/stress-test engine | **Implemented** |
| 5 | AlphaMemory™ — decision/institutional memory | **Implemented** |
| 6 | AlphaReplay™ — bitemporal historical reconstruction | **Implemented** |
| 7 | Chief Trading Agent full integration — AlphaSignal/AlphaConsensus feedback into trade generation, Overnight Intelligence Brief, Overview dashboard | **Implemented** |
| 8 | Enterprise Data Platform foundation — Workspace, connectors, admin onboarding UI | **Implemented (foundation)** |
| 9 | Tenant isolation retrofit — real `organization_id`/`workspace_id` enforcement, model routing policy, retention policy | Planned |
| 10 | Enterprise-specific Chief Trading Agent + Enterprise Digital Twin overlays + Opportunity Engine | Planned |

AlphaImpact through the Chief Trading Agent integration (2-7) are sequenced before the
Enterprise Data Platform (8-10) deliberately: they deliver real value against today's shared
public/simulated dataset first, and the harder structural work of true multi-tenant isolation
and proprietary connectors comes after there are six working components (plus a closed feedback
loop into trade generation) for enterprise data to plug into. AlphaReplay is last among the six
Alpha* components because it is the most invasive — it retrofits bitemporal columns onto
existing observation tables — so it's sequenced after the other five have real data worth
replaying. Chief Trading Agent integration comes last of all seven because it depends on every
other component already existing to have something real to feed back into trade generation and
summarize into a brief. Milestone 8 is marked "Implemented (foundation)" rather than a bare
"Implemented" deliberately: it delivers a genuine, testable `Workspace`/`EnterpriseDataSource`/
`EnterpriseDataset`/`EnterpriseDataEntitlement` foundation with one real connector
(`MANUAL_UPLOAD`), but real tenant-isolation enforcement, a `ModelRoutingPolicy`, and most of
the originally-envisioned admin tabs (Mappings/Lineage/Usage/Dependencies) are honestly still
Milestone 9-10 scope — see section 11 for the exact built-vs-not-built line.

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
is AlphaConsensus, section 6). Every other `SignalType` value exists on the schema for
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

**Enterprise personalization** (section 11's `ImpactAnalysis` "customer-specific view"
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

## 7. AlphaScenario™ (implemented)

**Purpose**: composes named and/or custom shocks into a richer counterfactual, then reuses
`risk_service/scenarios.py`'s existing, already-tested `run_scenario()` P&L/VaR math rather
than duplicating it — the same "extend, don't replace" relationship AlphaConsensus has with
the Quant team's models. Milestone 4 is honest about scope: it delivers shock *composition*
and *comparison*, not the full spec's per-geography/per-asset/duration-aware modeling — there
is no per-geography position or duration-decay data in this codebase today.

**Schema** (`packages/schemas/schemas/alpha.py`): `ScenarioFactorType` (the four shock
dimensions `risk_service.scenarios.Scenario` already supports: `PRICE_SHOCK_PCT`,
`DEMAND_SHOCK_BCF_D`, `SUPPLY_SHOCK_BCF_D`, `VOLATILITY_MULTIPLIER`); `ScenarioVariable` (one
composable shock factor — `geography`/`asset_id`/`duration` are accepted on the schema for
forward compatibility with the full spec but not yet used by the engine, always `None` until
that data model exists, the same honesty pattern as AlphaSignal's `novelty_score`);
`ScenarioDefinition` (zero or more `base_scenario_ids` from `risk_service.scenarios.SCENARIOS`
stacked with zero or more custom `ScenarioVariable`s); `ScenarioRunResult` (wraps
`risk_service.scenarios.ScenarioResult` with composition metadata and persistence identity);
`ScenarioComparison` (the "base vs. A vs. B vs. C" ranked comparison).

**Scenario engine** (`services/alpha/alpha_service/scenario_engine.py`): `ScenarioEngine` is
pure — no DB/LLM/event-bus access. `compose()` combines every named base scenario plus every
custom variable into one `risk_service.scenarios.Scenario`: price/demand/supply shocks are
summed (additive stacking of independent shocks), volatility multipliers are multiplied
(compounding uncertainty, matching AlphaImpact's decay philosophy that combining more shocks
never yields *more* certainty). `run()` composes then calls `risk_service.scenarios.
run_scenario()` directly — the underlying P&L/VaR math is never re-implemented.
`run_standing_library()` runs every entry in `risk_service.scenarios.SCENARIOS` (the
continuously-maintained standing stress-test library) against the same book in one pass;
`compare()` ranks any list of results worst-to-best by portfolio P&L impact.

**Integration** (`apps/api/api_app/state.py`): `AppState.run_alpha_scenario()` and
`run_alpha_scenario_comparison()` build the current paper book's `PositionSnapshot`s, call the
engine, persist via `ScenarioRunRow`, publish `SCENARIO_RUN`/`SCENARIO_COMPARISON_RUN`, and
append to a bounded in-memory `AppState.recent_scenario_runs` cache alongside the other
Alpha* caches.

**API**: `GET /alpha/scenarios/library` (the standing catalog, for a scenario picker),
`POST /alpha/scenarios/run` (composes and runs a named and/or custom scenario; 400 on an
unknown base scenario id), `POST /alpha/scenarios/compare` (runs the entire standing library
and ranks it), `GET /alpha/scenarios/runs`/`GET /alpha/scenarios/runs/{id}` (persisted run
history) — all gated by new `alpha_scenarios.view`/`alpha_scenarios.run` permissions, granted
to the same role set as `portfolio.view` (TRADER/RISK_MANAGER/RESEARCHER/EXECUTIVE, not
VIEWER, since a scenario run reveals portfolio P&L). These are additive to the pre-existing,
untouched `GET /risk/scenarios`/`POST /risk/scenarios/{id}/run` endpoints (which only ever ran
a single named scenario with no composition, comparison, or persistence).

**Chat tool**: the pre-existing `run_named_scenario` topic (permission unchanged,
`portfolio.view`) now detects an explicit percentage price move in the question ("...and
prices spike 20%") via `_extract_price_shock_pct()` — a modest, honest slice of "natural-
language-to-scenario parsing": regex extraction of a number plus a direction word, not a
general NLU parser — and stacks it onto the matched named scenario via `ScenarioEngine.
compose()` before running. A new `"scenario_comparison"` topic ("compare scenarios"/"stress
test my portfolio against every scenario"), permission `alpha_scenarios.view`, calls
`state.alpha_scenario_engine.run_standing_library()` directly (a pure, synchronous engine
call, no persistence) rather than the async `AppState` method — matching this project's
established provisional decision to keep the chat dispatch path synchronous rather than
making it async-aware for one topic.

**Dashboard**: a fourth "AlphaScenario" tab in the Alpha Intelligence sub-nav —
`/platform/alpha-intelligence/scenarios` (`ScenarioRunner.tsx`) lets a user pick a base
scenario plus an optional custom price-shock percentage, run it, run the entire standing
library and see it ranked, and browse recent run history.

**Enterprise personalization** (private stress scenarios against a workspace's own
portfolio/asset data) remains planned, not built — every `ScenarioRunResult` produced today is
platform-wide (`organization_id IS NULL`), since the Enterprise Data Platform milestones
(8-10) haven't been built.

## 8. AlphaMemory™ (implemented)

**Purpose**: preserves institutional memory of what was decided and what happened, so the
platform can distinguish a good decision from a good outcome across every closed trade, not
just in the moment. Milestone 5 is honest about scope: it builds only `DECISION_MEMORY`
records, for closed trades, linking only what is already, unambiguously `trade_id`-linked in
this codebase. It does **not** attempt to correlate a trade back to the `Signal`/
`ConsensusView`/`ScenarioRunResult` that may have informed it — no such link exists in the data
model today (no `TradeIdea` carries a `signal_id`), and guessing one via time-window
correlation would misrepresent an unverified guess as traceable evidence. Similarity search
across memories (structured/filter-based, later true vector-embedding similarity) and the
other nine `MemoryType` values remain future work.

**Schema** (`packages/schemas/schemas/alpha.py`): `MemoryType` (all ten values from the spec;
Milestone 5 only ever produces `DECISION_MEMORY`); `MemoryRecord` (`memory_type`, `trade_id`,
`market`, `strategy`, `title`, `summary`, `outcome_quadrant` — reusing the existing
`OutcomeQuadrant` enum from `docs/architecture.md`'s "Milestone 11" post-trade-analysis work
rather than inventing a parallel classification — `structured_context`, `tags`);
`LessonProposalStatus` (`PENDING`/`APPROVED`/`REJECTED`); `LessonProposal` (`memory_record_id`,
`proposed_lesson`, `rationale`, `status`, `reviewed_by`, `reviewed_at`).

**Memory builder + lesson engine** (`services/alpha/alpha_service/memory_builder.py`): both
pure — no DB/LLM/event-bus access. `MemoryBuilder.build_decision_memory()` assembles a
`MemoryRecord` from a closed trade's already-computed lifecycle objects (`TradeIdea`,
`InvestmentCommitteeDecision`, `RiskCheckResult`, `PostTradeAnalysis`, and the `PriceForecast`
attached at trade creation if any) — `summary` carries forward `PostTradeAnalysis.lessons`
verbatim (the same lessons string Milestone 11's `evaluate_post_trade()` already computes) and
`outcome_quadrant` carries forward `PostTradeAnalysis.quadrant` unchanged, never recomputed.
`LessonEngine.propose()` drafts a `LessonProposal` from a fixed template keyed off the memory's
`outcome_quadrant` — **not an LLM**, the same "no LLM in the engine path" discipline as
`MaterialityEngine`/`ImpactEngine`/`ConsensusEngine`/`ScenarioEngine`; genuinely LLM-drafted
lessons are future work. Returns `None` when the memory has no resolved outcome to learn from.

**Integration** (`apps/api/api_app/state.py`): `AppState._build_decision_memory()` runs
immediately after `close_trade()` persists its `PostTradeAnalysis`, turning that already-
computed record into a durable `MemoryRecord` plus a human-reviewable `LessonProposal` — never
an automatic feedback loop into any production model or threshold. Persists via
`MemoryRecordRow`/`LessonProposalRow`, publishes `MEMORY_RECORD_CREATED`/`LESSON_PROPOSED`, and
appends to bounded in-memory `AppState.recent_memory_records`/`recent_lesson_proposals` caches.
`AppState.review_lesson_proposal()` is the only way a proposal's status ever changes — approving
one still does not wire it back into any engine or threshold automatically.

**API**: `GET /alpha/memory` (30-day default window, since decision memory is meant to be
looked back on) and `GET /alpha/memory/{id}`; `GET /alpha/memory/lessons` (filterable by
`status`) and `GET /alpha/memory/lessons/{id}`; `POST /alpha/memory/lessons/{id}/review` (body
`{"status": "APPROVED"|"REJECTED"}`; 400 if asked to review back to `PENDING`). `alpha_memory.view`
is granted to TRADER/RISK_MANAGER/RESEARCHER/EXECUTIVE (not VIEWER, matching `alpha_scenarios.view`'s
reasoning — decision memory reveals real trade outcomes); `alpha_memory.review` is narrower still,
granted only to RISK_MANAGER/RESEARCHER — the two roles with a governance stake in what gets
codified as an institutional lesson.

**Chat tool**: a new `"decision_memory"` topic ("what have we learned"/"any lessons"/"decision
memory"), permission `alpha_memory.view`, reads `state.recent_memory_records`/
`recent_lesson_proposals` and narrates the most recent decision memories plus any lessons still
awaiting review — the natural conversational follow-up to AlphaConsensus's "Do the agents
agree?".

**Dashboard**: a fifth "AlphaMemory" tab in the Alpha Intelligence sub-nav —
`/platform/alpha-intelligence/memory` (`MemoryTable.tsx`) lists decision memories with their
full structured context, and a lesson-proposal review panel with inline Approve/Reject actions
gated by `alpha_memory.review`.

**Enterprise personalization** and the other nine `MemoryType` values remain planned, not
built — every `MemoryRecord` produced today is platform-wide (`organization_id IS NULL`), since
the Enterprise Data Platform milestones (8-10) haven't been built.

## 9. AlphaReplay™ (implemented)

**Purpose**: reconstructs what the Alpha Intelligence Layer itself knew and concluded as of a
chosen historical moment, under one hard rule — **only use information that was available at
that moment**, no look-ahead bias, no data revisions from the future. Milestone 6 is honest
about scope: it builds exactly one of the four replay modes the original spec described
(`CURRENT_MODEL_RETROSPECTIVE`), and documents precisely why the other three are not attempted
yet rather than approximating them:

- `HISTORICAL_REALITY` (a reconstruction of market reality itself, independent of what this
  platform recorded) — there is no persisted observation history prior to Milestone 6 shipping
  to reconstruct from; an `as_of` before then simply returns empty lists.
- `ORIGINAL_MODEL_REPLAY` (using the agent/model versions that actually existed at `as_of`) —
  `AgentVersionRow` (`docs/agent-governance.md §4`) tracks config snapshots per version, but
  nothing in this codebase yet re-executes an agent against a past version's config; wiring
  that is separate, not-yet-done work.
- `FULL_STRATEGY_REPLAY` (deterministic re-execution of the committee/risk/paper-execution
  pipeline against historical state) — that re-simulation machinery doesn't exist yet.

What Milestone 6 does build is genuine: real bitemporal persistence of market observations with
tested revision-supersession semantics, and real "as known at `<as_of>`" querying of the Alpha
Intelligence Layer's own already-timestamped history (Signals, Impact analyses, Consensus
views, Scenario runs, Decision memory).

**Bitemporal model** (`packages/schemas/schemas/observation.py`): `TimeSeriesObservation` now
carries two independent time axes. `observation_time`/`publication_time` (pre-existing) capture
*when the world was in a given state* vs. *when that became knowable*. New `revision_time`/
`valid_from`/`valid_to` additionally track *which revision of a given `series_id` +
`observation_time` was the current best estimate at any given moment* — when a later revision
arrives, the prior revision's `valid_to` is set to the new revision's `publication_time` rather
than overwritten, so an "as known at `<as_of>`" query can still recover exactly what was
believed then, corrections included. `valid_to` is `None` only for the current (latest)
revision. This is new, complementary infrastructure to `services/quant/quant_service/pit.py`'s
existing in-memory point-in-time-correctness helpers (used only by walk-forward backtesting),
not a replacement for them.

**DB + repository** (`packages/db/db/models.py`, `packages/db/db/repository.py`):
`MarketObservationRow` (table `market_observations`) mirrors `TimeSeriesObservation`
field-for-field. `save_market_observation()` finds the current (`valid_to IS NULL`) row for the
same `series_id` + `observation_time`; a revision number no higher than the current one is a
no-op (protects against duplicate/stale writes), otherwise the prior row's `valid_to` is closed
out at the new revision's `publication_time` and the new row is inserted as current — append-
only, nothing ever deleted or overwritten. `list_market_observations_as_of(series_id, as_of,
limit)` is the core bitemporal query: `publication_time <= as_of AND (valid_to IS NULL OR
valid_to > as_of)`, honoring later corrections exactly as they stood at `as_of`, not as they
stand today (see `tests/db/test_market_observations.py` for the revision-supersession and
as-of-before-a-correction proofs). Every other Alpha* list method
(`list_signals`/`list_impact_analyses`/`list_consensus_views`/`list_scenario_runs`/
`list_memory_records`) gained an `until` parameter (`list_consensus_views`/`list_memory_records`
also gained `market`), so "as known at `<as_of>`" filtering happens in exactly one place per
table rather than being reimplemented per caller.

**Replay engine** (`services/alpha/alpha_service/replay_engine.py`): `ReplayEngine.assemble()`
is a thin, pure packaging function — all real bitemporal correctness lives in the repository
queries above, not here, so there is exactly one place look-ahead bias could be introduced.

**Integration** (`apps/api/api_app/state.py`): `AppState._persist_market_observations()` is
called right after the market curve is fetched each cycle, so real observation history
accumulates from Milestone 6's deployment forward. `AppState.compute_as_of_replay(market, as_of,
organization_id)` fetches every Alpha* series `until`/`as_of` and hands the results to
`ReplayEngine.assemble()`.

**API**: `GET /alpha/replay` (`market`, `as_of` — defaults to now), gated by
`alpha_replay.view` (granted to TRADER/RISK_MANAGER/RESEARCHER/EXECUTIVE, not VIEWER — the
bundled scenario runs/decision memory aren't otherwise visible to VIEWER).

**Chat tool**: a new `"replay_snapshot"` topic ("time machine"/"as of"/"what did we know"),
permission `alpha_replay.view`. This is the first Alpha* chat topic that cannot be answered from
a bounded in-memory cache — its answer requires an arbitrary-timestamp bitemporal query — so
`ChatAgent._dispatch()` became `async def` (a purely mechanical change; every other topic method
stays synchronous and unaffected) to let `_replay_snapshot()` `await
state.compute_as_of_replay()` directly. Parses an explicit `YYYY-MM-DD[ HH:MM[:SS]]` from the
question if present, defaulting to now otherwise — not a general date-NLU parser.

**Dashboard**: a sixth "AlphaReplay" tab in the Alpha Intelligence sub-nav —
`/platform/alpha-intelligence/replay` (`ReplaySnapshot.tsx`) with an as-of timestamp picker and
a "Now" shortcut, rendering the resulting snapshot's price observations, signals, impacts,
consensus views, scenario runs, and decision memory as separate panels, each honestly showing
"No … recorded as of this moment" rather than a placeholder value when a list is empty.

**Market Time Machine UI** (a step-through "replay Winter Storm Uri" chronological experience)
and the other three replay modes remain future work, sequenced after real historical volume
accumulates.

## 10. Chief Trading Agent full integration (implemented)

**Purpose**: every Alpha* component through Milestone 6 ran strictly *after* a `TradeIdea`
already existed — a parallel, downstream analysis layer that never fed back into trade
generation itself. Milestone 7 closes that loop and adds the two remaining pieces from the
original Milestone 7 scope (the Overnight Intelligence Brief and an Overview dashboard tying
all six components together).

**AlphaSignal/AlphaConsensus feedback into trade generation**
(`services/alpha/alpha_service/trading_integration.py`): restructuring `DirectionalStrategyAgent`
itself to read Alpha* output was rejected as too invasive — it would risk destabilizing
already-tested trade-generation logic for uncertain benefit. Instead, `AlphaCorroborationEngine`
(pure, no DB/LLM/event-bus access) cross-checks a freshly-generated `TradeIdea` against fresh
AlphaSignal output and the latest AlphaConsensus view, and `AppState.submit_trade_idea()` — the
single choke point every trade idea passes through, in both `_run_initial_research_cycle` and
`run_chief_trading_cycle`, before the Investment Committee ever sees it — merges the result onto
the trade's own `catalysts`/`supporting_data`/`source_citations`/`risks` fields. This is a real
integration, not cosmetic: `BullAgent` reads `trade.catalysts` and `SkepticAgent` reads
`trade.source_citations`/`trade.supporting_data`, so a corroborating or contradicting signal
genuinely reaches committee deliberation. Deliberately conservative: a signal only corroborates
or cautions a trade when it clears `DEFAULT_MATERIALITY_THRESHOLD` and has a clear directional
lean (`SignalDirection.BULLISH`/`BEARISH`) matched against the trade's `Direction`
(`LONG`/`SHORT`) — a `SPREAD` trade or a `NEUTRAL` signal is never scored as aligned or opposed,
since there is no principled directional read for either.

**Overnight Intelligence Brief** (`services/alpha/alpha_service/brief_engine.py`): a single
cross-component digest of what AlphaSignal/AlphaImpact/AlphaConsensus/AlphaScenario/AlphaMemory
each concluded over the last 16 hours (an overnight window, not a full day, since it's generated
once per full research cycle rather than on a calendar schedule). `BriefEngine.compose()` is
pure — it never queries anything itself, only ranks/selects already-computed, already-persisted
records the caller hands it. `headline`/`summary` are composed from fixed templates, not an LLM
— the same "no LLM in the engine path" discipline as every other Alpha* engine.
`AppState.generate_intelligence_brief()` fetches the period's signals/impacts/consensus views/
scenario runs/pending lesson proposals, persists the result via `IntelligenceBriefRow`, and
publishes `INTELLIGENCE_BRIEF_GENERATED`. Only reachable from `_run_initial_research_cycle`
(boot's full cycle) — `run_chief_trading_cycle`'s lighter on-demand path doesn't generate a
brief, matching the same boot-cycle-only scope already established for `_run_alpha_consensus`.
Exposed via `GET /alpha/briefs/latest`, `GET /alpha/briefs`, `GET /alpha/briefs/{id}` (new
`alpha_brief.view` permission, granted to TRADER/RISK_MANAGER/RESEARCHER/EXECUTIVE, not VIEWER),
and a new `"overnight_brief"` chat topic ("overnight brief"/"morning brief"/"daily brief").

**Overview dashboard** — a new root page at `/platform/alpha-intelligence`
(`AlphaOverview.tsx`) renders the latest Overnight Intelligence Brief plus six link cards, one
per component, tying the whole layer together. The top-level "Alpha Intelligence" nav link now
points here instead of straight to `/signals`; the sub-nav gained a leading "Overview" tab.

**Not built**: personalized enterprise briefs (needs the Enterprise Data Platform, Milestones
8-10 below); a scheduled/calendar-triggered brief generation cadence (today's brief is generated
once per boot/full research cycle, not on a fixed schedule); brief-to-brief diffing ("what
changed since yesterday's brief").

## 11. Enterprise Data Platform (foundation implemented — Milestone 8; Milestones 9-10 planned)

**Milestone 8 delivers a genuine, testable foundation**: an admin can register a `Workspace`,
register an `EnterpriseDataSource`, run it through a real `BaseEnterpriseDataConnector`
(schema discovery, preview, ingest), register `EnterpriseDataset`s, and grant
`EnterpriseDataEntitlement`s — all persisted, all API- and UI-reachable. It is honest about
scope: real multi-tenant *row-level isolation* (Postgres RLS or equivalent), a
`ModelRoutingPolicy`, and most of the originally-envisioned admin tabs remain Milestones 9-10,
not silently assumed to already exist.

### 11.1 Multi-tenant architecture

**Implemented**: `Workspace` (`packages/schemas/schemas/enterprise.py`) — a grouping inside an
`Organization`, layered on top of the existing `Organization`/`Role`/`Permission`/`Feature`
tables rather than replacing them, with membership (`WorkspaceMemberRow`) managed via
`POST/DELETE /admin/workspaces/{id}/members`. Every enterprise data object carries
`organization_id`, `workspace_id` (where applicable), and a security-tier classification.
`AgentDataEntitlement` from the original plan is unified into one `EnterpriseDataEntitlement`
table via a `principal_type` discriminator (`USER`/`ROLE`/`WORKSPACE`/`AGENT`) rather than a
structurally-identical parallel table — recording the grant is Milestone 8's scope; no agent
reads an enterprise dataset today, so per-agent runtime enforcement of an `AGENT`-typed grant
remains future work, honestly undocumented as built until it exists.

**Not yet built**: `DataEntitlement`/`ModelEntitlement`/`Portfolio` as originally sketched
(subsumed or deferred), and — the significant gap — **real tenant isolation is not enforced**.
Every `organization_id`/`workspace_id` column exists and every admin list endpoint filters by
it when given, but there is no PostgreSQL Row Level Security (or equivalent) making that
filtering unbypassable at the database layer, and no verified-tenant-context propagation
through every service call. That retrofit — across both these new tables and every existing
trading table — is Milestone 9's job specifically, not assumed here.

### 11.2 Security-tier data classification

**Implemented**: `EnterpriseDataClassification` (`PUBLIC`/`LICENSED_MARKET_DATA`/
`ALPHAGASIQ_PROPRIETARY`/`CUSTOMER_CONFIDENTIAL`/`CUSTOMER_RESTRICTED`/
`CUSTOMER_POSITION_DATA`/`CUSTOMER_RISK_DATA`/`SIMULATED`) — a new enum, deliberately distinct
from the existing `DataClassification` (a data-provenance tag, not a security tier; see
section 2). Every `EnterpriseDataSource`/`EnterpriseDataset` carries one. **Not yet built**:
the full access-rule combination (organization + workspace + role + permission + this
classification + feature entitlement + dataset entitlement + agent entitlement) described in
the original plan — today only `admin.enterprise_data`/`admin.workspaces` gate the whole admin
surface; per-dataset entitlement-based access control for a *non-admin* caller (e.g. a trader
reading only datasets their workspace was granted) is not wired into any read path yet.

### 11.3 Enterprise data connectors

**Implemented**: `BaseEnterpriseDataConnector` (`services/enterprise_data/
enterprise_data_service/connector.py`) — `test_connection()`/`discover_schema()`/`preview()`/
`ingest()`/`health_check()`, the same abstraction shape `data_sdk.provider.BaseDataProvider`
already established, trimmed from the original ten-method sketch
(`connect`/`authenticate`/`incremental_sync`/`validate`/`normalize`/`disconnect` dropped) down
to what's actually implementable without overengineering — `BaseDataProvider` itself only
ships three methods, not its own doc's full list either. Exactly one connector type is
implemented end-to-end: `ManualUploadConnector` (`MANUAL_UPLOAD`) — an admin supplies
already-parsed tabular rows (the admin UI parses a pasted CSV client-side), no external network
call, no credential, genuinely usable with zero paid subscriptions, the same discipline every
`Mock*Provider` already establishes for public/licensed connectors. `REST_API`/`SFTP`/
`DATABASE`/`S3`/`WEBHOOK` are declared on `EnterpriseConnectorType` for forward-compatibility
only — a source of one of those types can be registered, but `build_connector()` returns a
`NotImplementedConnector` for it, which reports `not_configured`/raises `NotImplementedError`
honestly rather than silently behaving like `MANUAL_UPLOAD`. Real REST/SFTP/database/S3/webhook
connector implementations remain future work.

### 11.4 Admin onboarding, canonical model, and safeguards

**Implemented**: an Admin "Enterprise Data" page (source list/create, per-source "Test
Connection" + event log, per-source dataset list/create with schema discovery from sample
rows, per-dataset preview/ingest + records list, per-dataset entitlement grant/list/revoke) and
a separate "Workspaces" page (list/create/delete, member add/remove) —
`apps/web/components/admin/enterprise-data/EnterpriseDataConsole.tsx` and `apps/web/app/
platform/admin/workspaces/page.tsx`. `EnterpriseDataSourceRow` deliberately carries no
credential/secret field — exactly `DataFeedConfigRow`'s existing posture: real secrets would be
environment-provisioned and never touch this table or the admin API (moot today since the only
implemented connector needs no credential at all). `EnterpriseDataDomain` (the canonical
`MARKET_PRICE`/`PRODUCTION`/`DEMAND`/.../`FLOW` domain enum) exists and every dataset declares
one, but ingested rows are stored as an opaque `EnterpriseRecordRow.row_data` JSON blob — there
is no per-domain typed table, and wiring ingested rows into the same rich, typed
`ObservationDraft` canonical model market data already uses is future work, documented here
rather than silently assumed.

**Not yet built**: a Mappings tab (field/unit/timezone mapping UI — schema discovery exists,
but there's no UI to remap a discovered field to a canonical name/unit); a dedicated Lineage
tab; a Usage analytics tab; a Dependencies tab (which agents/features depend on which dataset —
`EnterpriseDataEntitlement`'s `AGENT` principal type records a grant, but nothing surfaces "what
depends on this dataset" the way `admin/data-feeds/dependency-map` does for the built-in feeds);
retention-policy fields/enforcement; a `ModelRoutingPolicy` gating `LLMProvider`
(`packages/agent-sdk/agent_sdk/llm.py`) by classification — every `CUSTOMER_RESTRICTED` dataset
today is exactly as reachable by any configured LLM provider as any other, since nothing reads
this classification at LLM-call time yet; and the broader data-loss-prevention posture (logs,
monitoring payloads, cross-organization vector search never leaking one customer's confidential
data into another's outputs) the original plan described. All of this is Milestone 9/10 scope.

## 12. Transparency and explainability

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
