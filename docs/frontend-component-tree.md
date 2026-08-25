# Frontend Component Tree

`apps/web` — Next.js 14 App Router, TypeScript, Tailwind CSS, dark institutional trading-terminal
theme (no gamification, no consumer-brokerage styling). Shared primitives live in
`packages/ui`.

```
app/
├── layout.tsx                     Root layout: theme, auth guard, SystemStatusProvider
├── (dashboard)/
│   ├── layout.tsx                 Dashboard shell: <HeaderBar/> + <NavRail/> + content grid
│   └── page.tsx                   Composes the panels below
├── trade-ideas/[tradeId]/page.tsx  Trade idea explainability detail view
├── pipeline-map/page.tsx           Full-screen pipeline digital twin
├── chat/page.tsx                   Full AI Trader Chat view
└── admin/risk-limits/page.tsx      Risk limit configuration (RISK_MANAGER/ADMIN)

components/
├── header/
│   └── HeaderBar.tsx                HH M1, daily %, M2, 12-mo strip, NAV, daily/unrealized P&L,
│                                     VaR, AI market bias, <SystemStatusBadge/>
├── market-intel/
│   ├── MarketIntelGrid.tsx
│   └── MarketIntelCard.tsx          production / LNG feedgas / power burn / rescom demand /
│                                     Mexico exports / storage forecast / weather HDD change
├── curve/
│   ├── ForwardCurveChart.tsx        TradingView Lightweight Charts, M1-M36
│   └── CurveCompareToggle.tsx       current / prev settlement / 1wk / 1mo overlays
├── storage/
│   └── StoragePanel.tsx             current / forecast / 5yr avg / yr-ago / EOS projection
├── weather/
│   ├── WeatherPanel.tsx             ECMWF / GFS / ensemble HDD-CDD summary
│   ├── ModelRunDeltaTable.tsx       WeatherDemandImpact rows
│   └── RegionalTempMap.tsx          Mapbox/deck.gl regional temperature overlay
├── pipeline-map/
│   ├── PipelineMap.tsx              Mapbox/deck.gl network: pipelines/storage/basins/LNG/power
│   └── PipelineNodeInspector.tsx    node/edge detail drawer
├── recommendations/
│   ├── RecommendationCard.tsx       trade/entry/target/invalidation/return/probability/
│   │                                 confidence/thesis/catalysts/risks + <ChallengeAiButton/>
│   ├── ChallengeAiButton.tsx        invokes POST /trade-ideas/{id}/challenge
│   └── ExplainabilityPanel.tsx      WHAT/WHY/WHY NOW/CATALYST/EXPECTED OUTCOME/
│                                     ALTERNATIVE VIEW/INVALIDATION/CONFIDENCE/DATA QUALITY/
│                                     RISK/SOURCES
├── risk/
│   ├── RiskSummaryCard.tsx          gross/net exposure, greeks, VaR/ES, drawdown
│   └── ScenarioRunner.tsx           stress-test scenario picker + results
├── approvals/
│   └── ApprovalQueue.tsx            human-in-the-loop actions on pending trade ideas
├── chat/
│   ├── ChatPanel.tsx                persistent AI Trader Chat (docked + full-page variants)
│   ├── ChatMessage.tsx              renders citations/freshness/source badges inline
│   └── ChatComposer.tsx
├── status/
│   ├── SystemStatusBadge.tsx
│   └── FreshnessTag.tsx             reusable "stale" indicator used across all data-bearing cards
└── common/
    ├── DataSourceBadge.tsx          PUBLIC / LICENSED / USER_PROVIDED / SIMULATED chip
    ├── ConfidenceMeter.tsx
    └── DensityTable.tsx             shared high-density table primitive

lib/
├── api-client.ts                   typed fetch wrapper against apps/api
├── auth.ts                         session/JWT handling
└── ws.ts                           chat + live-tick WebSocket client
```

Design rules (enforced via `packages/ui` tokens): dark background, information-dense tables over
large charts, every numeric card carries a `<FreshnessTag/>` and, where applicable, a
`<DataSourceBadge/>`. Simulated data is always visibly labeled `SIMULATED` — this is a hard UI
rule, not a style preference, since the MVP boots entirely on seed data.
