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
| Fundamentals | EIA API (Natural Gas Weekly/Monthly, Storage) | PUBLIC | **Implemented** (`services/data/data_service/providers/eia.py`) |
| Weather | NOAA / National Weather Service API | PUBLIC | **Implemented** (`services/data/data_service/providers/noaa.py`) |
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
- Weather: tied to model run cycle (e.g. GFS every 6h, ECMWF every 12h)
- News: minutes
- EIA: tied to weekly/monthly release schedule

## 5. Storage of Raw Payloads

Raw provider responses are archived to S3-compatible object storage
(`ObjectStore` interface, MinIO in dev) keyed by `provider_id/date/request_hash`, referenced from
`observations.lineage`, so any normalized value can be traced back to the exact raw payload that
produced it.
