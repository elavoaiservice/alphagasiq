# Data Sources & Provider Platform

## 1. Provider Abstraction

All external data enters through a connector implementing `BaseDataProvider`
(`packages/data-sdk/provider.py`):

```python
class BaseDataProvider(ABC):
    provider_id: str
    classification: DataClassification   # PUBLIC | LICENSED | USER_PROVIDED | SIMULATED
    freshness_sla_seconds: int | None

    async def health_check(self) -> ProviderHealth: ...
    async def fetch(self, request: FetchRequest) -> list[ObservationDraft]: ...
    def normalize(self, raw: Any) -> list[ObservationDraft]: ...
```

`ObservationDraft` maps 1:1 onto the canonical `observations` row (see
`docs/database-schema.md`), always including `source`, `source_type`, `publication_time`, and
`lineage`. A `ProviderRegistry` looks providers up by id and enforces that every registered
provider declares its classification — there is no "unclassified" data path.

Every provider that could involve a paid/licensed feed ships with a `Mock*Provider` sibling
producing realistic, clearly-`SIMULATED` data, so the platform is fully demoable with
`docker compose up` and zero commercial credentials.

## 2. Classification Policy

| Class | Meaning | Examples |
|---|---|---|
| `PUBLIC` | Freely available government/public data, used per each source's terms | EIA API, NOAA/NWS, FERC public filings, SEC EDGAR, ISO/RTO public feeds, public RSS/Atom news |
| `LICENSED` | Requires a commercial entitlement; never assumed free | CME market data, ICE data, licensed news wires |
| `USER_PROVIDED` | Uploaded/pasted by a human user | manually entered positions, analyst notes |
| `SIMULATED` | Synthetic seed/demo data | `MockCMEProvider`, `MockNewsProvider`, `MockWeatherProvider` output |

The platform **never scrapes a site in violation of its terms of service**, and never assumes
market data is free — `LICENSED` connectors require explicit API credentials in `.env` and are
disabled (falling back to their mock) when credentials are absent.

## 3. Initial Connector Roster

| Domain | Provider | Classification | MVP Status |
|---|---|---|---|
| Fundamentals | EIA API (weekly storage, monthly production/consumption by sector, Henry Hub futures front-month, LNG exports) | PUBLIC | **Implemented** (`services/data/data_service/providers/eia.py`, `EIA_SERIES_MAP`) — Phase 1 free-data-feed round expanded this from 2 series (storage, production) to 8; new routes are asserted from EIA's documented v2 API structure, not live-verified (this sandbox has no outbound network access to EIA), so treat each as "ship pending first live verification," failing loud (a non-2xx `raise_for_status()`, surfaced through the admin Data Feeds panel) rather than silently wrong if a route/facet turns out mismatched |
| Weather | NOAA / National Weather Service API (forecast temperature, active severe-weather alerts, a national HDD/CDD approximation) | PUBLIC | **Implemented** (`services/data/data_service/providers/noaa.py`) — the national HDD/CDD figure is an unweighted average across tracked regions, explicitly *not* claimed to be population-weighted |
| Regulatory | FERC public data (eLibrary/eTariff indices) | PUBLIC | Interface defined, connector stub — no single stable public JSON API to build a real connector against with confidence (eLibrary is a document-search portal, not a queryable API); see `providers/stubs.py` |
| Pipeline ops | Public pipeline bulletin-board / operational feeds (where legally accessible) | PUBLIC | Interface defined, connector stub — no common schema across pipeline operators' bespoke EBB sites |
| Power | ISO/RTO public feeds (EIA-930-derived hourly generation-by-fuel for PJM/CAISO/ERCOT/MISO/SPP) | PUBLIC | **Implemented** (`services/data/data_service/providers/iso_rto.py`, `ISORTOProvider`) — reuses the EIA v2 API's proven auth/request shape rather than each ISO's own bespoke market-data API |
| Corporate | SEC EDGAR company-filings API (recent 8-K/10-K/10-Q for tracked natural-gas-relevant companies) | PUBLIC | **Implemented** (`services/data/data_service/providers/sec_edgar.py`, `SECEdgarProvider`) — no API key required, only a descriptive `User-Agent`/contact per SEC's fair-access policy |
| News | RSS/Atom feeds | PUBLIC | **Implemented** (`services/data/data_service/providers/rss_news.py`) + `MockNewsProvider` |
| News | Licensed commercial news providers | LICENSED | Adapter interface + `MockLicensedNewsProvider` |
| Market data | CME (properly entitled API) | LICENSED | Adapter interface + `MockCMEProvider` (**implemented**, default in dev) |
| Market data | ICE (properly licensed API, where available) | LICENSED | Adapter interface + `MockICEProvider` |

Connectors not yet built ship as a typed interface plus a `NotImplementedProvider` that reports
`ProviderHealth(status="not_configured")` — visible in the system-status dashboard rather than
silently missing.

## 4. Freshness

Every provider declares a `freshness_sla_seconds`. The API exposes a `/system/freshness`
endpoint and the UI renders stale-state badges wherever data from that provider is shown.
Indicative defaults:

- Market prices (mock/live): seconds
- Pipeline data: hours (bulletin-board cadence)
- Weather: tied to NOAA/NWS's own forecast-update cadence (several times per day) — never
  labeled GFS/ECMWF unless a connector for one of those specific model products actually exists;
  `weather_kwargs["model"]` reports exactly which source produced the figures in use
- News: minutes
- EIA: tied to weekly/monthly release schedule

Beyond the raw `freshness_seconds` above, `data_sdk.compute_freshness_status()` (Phase 1
free-data-feed round, spec §12) derives a `LIVE`/`CURRENT`/`DELAYED`/`STALE`/`FAILED`/`UNKNOWN`
state from how old the latest *successfully ingested* observation is relative to that cadence —
a successful API response alone is never treated as proof of currency. Surfaced via
`GET /admin/data-feeds` as `freshness_status`.

## 5. Storage of Raw Payloads

Raw provider responses are archived to S3-compatible object storage
(`ObjectStore` interface, MinIO in dev) keyed by `provider_id/date/request_hash`, referenced from
`observations.lineage`, so any normalized value can be traced back to the exact raw payload that
produced it.

## 6. Data Quality Scoring (Phase 1 free-data-feed round, spec §13)

`DataQualityService` (`services/data/data_service/quality.py`) computes a deterministic 0-100
score per `ObservationDraft` — missing/impossible values (negative storage/production, an
implausible temperature), a future-dated observation, and a >5x jump against the prior
observation for the same series. Never delegated to an LLM. Attached to
`ObservationDraft.quality_score` (stored as a 0-1 fraction, matching that field's existing
convention) when observations are persisted, and averaged per ingestion batch into
`DataFeedEventRow.avg_quality_score` — the `data_quality_score` `GET /admin/data-feeds` reports
(0-100), previously always `None`.

## 7. Wiring Real Data Into the Live Engine (Phase 1 free-data-feed round)

Every connector above existed but, until this round, was never actually called by the running
application outside an admin-triggered manual refresh — `AppState._seed_market_and_fundamentals()`
populated the fundamentals engine's inputs entirely from `fundamentals_service/seed.py`'s
synthetic generators, and `worker.py`'s periodic loop hardcoded a fake `weather_kwargs` dict that
falsely claimed "GFS" or "ECMWF" without ever calling either. `AppState.
refresh_fundamentals_from_public_data()` closes this gap for the two fields whose real source
data is granular enough to use honestly:

- **`storage_baseline`**: real EIA weekly storage history (current inventory, year-ago, 5-year
  average/low/high computed from real historical prints — not interpolated) once `EIA_API_KEY`
  is configured; left untouched, not blended with synthetic data, when it isn't.
- **`weather_kwargs`**: real NOAA national HDD/CDD, diffed against the previous refresh's
  snapshot — NOAA needs no API key, so this updates unconditionally, replacing the fallback
  `model="SIMULATED_FALLBACK"` with `model="NOAA_NWS_FORECAST"`.

Deliberately does **not** touch `self.balances` (`GasBalanceDaily`, one row per day): EIA
publishes natural gas fundamentals weekly/monthly, never daily — interpolating a fake daily
shape from monthly totals would be estimation presented as real precision it doesn't have.
`self.balances`, `lng_terminals`, and `power_markets` stay the existing, honestly-`SIMULATED`
daily/seed generators (`MarketIntelGrid`'s dashboard cards say so) until a real
daily-granularity free source exists — explicitly deferred, not an oversight.

Called once at boot and on every `worker.py` cycle (a new fourth try/except block, same pattern
as the existing three), before the research cycle that consumes `storage_baseline`/
`weather_kwargs` runs — so AlphaSignal detection and the Chief Trading Agent's research cycle
work off real figures whenever they're configured.
