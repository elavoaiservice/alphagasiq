import asyncio
from datetime import datetime, timezone

import httpx
import pytest
from data_service.providers.eia import EIAProvider
from data_service.providers.iso_rto import ISORTOProvider
from data_service.providers.mock_market_data import MockCMEProvider, MockICEProvider
from data_service.providers.mock_news import MockNewsProvider
from data_service.providers.noaa import NOAAProvider, degree_days
from data_service.providers.sec_edgar import SECEdgarProvider
from data_service.registry import build_default_registry
from data_sdk import FetchRequest
from schemas import DataClassification


def test_eia_normalize_produces_public_observations():
    provider = EIAProvider(api_key="fake-key")
    raw = {
        "series_id": "EIA.NG.STORAGE.LOWER48",
        "spec": {"route": "natural-gas/stor/wkly/data", "category": "STORAGE", "unit": "BCF"},
        "raw": {"response": {"data": [{"period": "2026-08-14", "value": "3200"}]}},
    }
    drafts = provider.normalize(raw)
    assert len(drafts) == 1
    assert drafts[0].source_type == DataClassification.PUBLIC
    assert drafts[0].value == 3200.0
    assert drafts[0].category == "STORAGE"


def test_eia_normalize_skips_missing_values():
    provider = EIAProvider(api_key="fake-key")
    raw = {
        "series_id": "x",
        "spec": {"route": "r", "category": "STORAGE", "unit": "BCF"},
        "raw": {"response": {"data": [{"period": "2026-08-14"}]}},
    }
    assert provider.normalize(raw) == []


@pytest.mark.asyncio
async def test_eia_fetch_returns_nothing_without_api_key():
    provider = EIAProvider(api_key=None)
    result = await provider.fetch(FetchRequest())
    assert result == []
    health = await provider.health_check()
    assert health.status == "not_configured"


@pytest.mark.asyncio
async def test_eia_fetch_henry_hub_series_sends_facet_and_daily_frequency():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(
            200, json={"response": {"data": [{"period": "2026-08-27", "value": "2.85"}]}}
        )

    transport = httpx.MockTransport(handler)
    provider = EIAProvider(api_key="fake-key", client=httpx.AsyncClient(transport=transport))
    drafts = await provider.fetch(FetchRequest(series_ids=["EIA.NG.PRICE.HENRY_HUB_FUTURES_FRONT_MONTH"]))

    assert len(drafts) == 1
    assert drafts[0].category == "MARKET_PRICE"
    assert drafts[0].sub_category == "HENRY_HUB_FUTURES_FRONT_MONTH"
    assert drafts[0].value == 2.85
    assert drafts[0].license_type == "PUBLIC_DOMAIN_GOVERNMENT_DATA"
    assert drafts[0].redistribution_allowed is True
    assert captured["params"]["frequency"] == "daily"
    assert captured["params"]["facets[series][0]"] == "RNGC1"


@pytest.mark.asyncio
async def test_eia_fetch_consumption_series_sends_process_facet():
    def handler(request: httpx.Request) -> httpx.Response:
        assert dict(request.url.params)["facets[process][0]"] == "VRS"
        return httpx.Response(200, json={"response": {"data": [{"period": "2026-07", "value": "700"}]}})

    transport = httpx.MockTransport(handler)
    provider = EIAProvider(api_key="fake-key", client=httpx.AsyncClient(transport=transport))
    drafts = await provider.fetch(FetchRequest(series_ids=["EIA.NG.CONSUMPTION.RESIDENTIAL"]))

    assert len(drafts) == 1
    assert drafts[0].category == "DEMAND"
    assert drafts[0].sub_category == "RESIDENTIAL_CONSUMPTION"


@pytest.mark.asyncio
async def test_eia_fetch_storage_respects_length_override():
    def handler(request: httpx.Request) -> httpx.Response:
        assert dict(request.url.params)["length"] == "260"
        return httpx.Response(200, json={"response": {"data": []}})

    transport = httpx.MockTransport(handler)
    provider = EIAProvider(api_key="fake-key", client=httpx.AsyncClient(transport=transport))
    await provider.fetch(FetchRequest(series_ids=["EIA.NG.STORAGE.LOWER48"], extra={"length": 260}))


@pytest.mark.asyncio
async def test_eia_fetch_raises_on_http_error():
    transport = httpx.MockTransport(lambda request: httpx.Response(500, json={"error": "boom"}))
    provider = EIAProvider(api_key="fake-key", client=httpx.AsyncClient(transport=transport))
    with pytest.raises(httpx.HTTPStatusError):
        await provider.fetch(FetchRequest(series_ids=["EIA.NG.STORAGE.LOWER48"]))


@pytest.mark.asyncio
async def test_eia_fetch_lng_imports_series():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"response": {"data": [{"period": "2026-06", "value": "3"}]}})
    )
    provider = EIAProvider(api_key="fake-key", client=httpx.AsyncClient(transport=transport))
    drafts = await provider.fetch(FetchRequest(series_ids=["EIA.NG.LNG.IMPORTS"]))

    assert len(drafts) == 1
    assert drafts[0].category == "LNG"
    assert drafts[0].sub_category == "LNG_IMPORTS"
    assert drafts[0].value == 3.0
    assert drafts[0].license_type == "PUBLIC_DOMAIN_GOVERNMENT_DATA"


@pytest.mark.asyncio
async def test_eia_fetch_lng_exports_series():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"response": {"data": [{"period": "2026-06", "value": "820"}]}})
    )
    provider = EIAProvider(api_key="fake-key", client=httpx.AsyncClient(transport=transport))
    drafts = await provider.fetch(FetchRequest(series_ids=["EIA.NG.LNG.EXPORTS"]))

    assert len(drafts) == 1
    assert drafts[0].category == "LNG"
    assert drafts[0].sub_category == "LNG_EXPORTS"
    assert drafts[0].value == 820.0


def test_degree_days_hot_day():
    hdd, cdd = degree_days(90.0)
    assert hdd == 0.0
    assert cdd == 25.0


def test_degree_days_cold_day():
    hdd, cdd = degree_days(20.0)
    assert hdd == 45.0
    assert cdd == 0.0


def test_noaa_normalize_computes_degree_days():
    provider = NOAAProvider(contact_token="test@example.com")
    raw = {
        "region": "US_NATIONAL",
        "raw": {
            "properties": {
                "periods": [
                    {"temperature": 30, "startTime": "2026-01-15T00:00:00-05:00", "name": "Tonight", "isDaytime": False}
                ]
            }
        },
    }
    drafts = provider.normalize(raw)
    assert len(drafts) == 1
    assert drafts[0].metadata["hdd"] == 35.0
    assert drafts[0].source_type == DataClassification.PUBLIC


def _noaa_response_for(request: httpx.Request) -> httpx.Response:
    if "/alerts/active" in request.url.path:
        return httpx.Response(
            200,
            json={
                "features": [
                    {
                        "properties": {
                            "id": "urn:test:alert1",
                            "event": "Winter Storm Warning",
                            "severity": "Severe",
                            "certainty": "Likely",
                            "urgency": "Expected",
                            "areaDesc": "Northern Plains",
                            "onset": "2026-01-14T00:00:00-05:00",
                            "expires": "2026-01-16T00:00:00-05:00",
                            "headline": "Winter Storm Warning issued",
                        }
                    }
                ]
            },
        )
    return httpx.Response(
        200,
        json={
            "properties": {
                "periods": [
                    {"temperature": 20, "startTime": "2026-01-15T00:00:00-05:00", "name": "Tonight", "isDaytime": False}
                ]
            }
        },
    )


@pytest.mark.asyncio
async def test_noaa_fetch_includes_alerts_and_national_hdd_cdd_average():
    transport = httpx.MockTransport(_noaa_response_for)
    provider = NOAAProvider(contact_token="test@example.com", client=httpx.AsyncClient(transport=transport))
    drafts = await provider.fetch(FetchRequest(extra={"regions": ["NORTHEAST"]}))

    alert_drafts = [d for d in drafts if d.sub_category == "SEVERE_WEATHER_ALERT"]
    assert len(alert_drafts) == 1
    assert alert_drafts[0].metadata["event"] == "Winter Storm Warning"
    assert alert_drafts[0].license_type == "PUBLIC_DOMAIN_GOVERNMENT_DATA"

    national_drafts = [d for d in drafts if d.sub_category == "NATIONAL_HDD_CDD_UNWEIGHTED_APPROXIMATION"]
    assert len(national_drafts) == 1
    assert national_drafts[0].metadata["hdd"] == 45.0  # degree_days(20.0) -> hdd=45
    assert national_drafts[0].geography == "US_NATIONAL"


@pytest.mark.asyncio
async def test_noaa_fetch_skips_national_average_when_no_recognized_regions():
    transport = httpx.MockTransport(_noaa_response_for)
    provider = NOAAProvider(contact_token="test@example.com", client=httpx.AsyncClient(transport=transport))
    # An unrecognized region key has no matching station, so no forecast is fetched
    # for it -- unlike an empty/falsy `regions` list, which (like EIA's `series_ids`)
    # falls back to the full default set rather than "fetch nothing."
    drafts = await provider.fetch(FetchRequest(extra={"regions": ["NOT_A_REAL_REGION"]}))
    assert not any(d.sub_category == "NATIONAL_HDD_CDD_UNWEIGHTED_APPROXIMATION" for d in drafts)
    # Alerts are still fetched even with no forecast regions configured.
    assert any(d.sub_category == "SEVERE_WEATHER_ALERT" for d in drafts)


def test_iso_rto_normalize_produces_public_power_burn_observations():
    provider = ISORTOProvider(api_key="fake-key")
    raw = {
        "respondent": "PJM",
        "raw": {
            "response": {
                "data": [
                    {
                        "period": "2026-08-25T14",
                        "respondent": "PJM",
                        "respondent-name": "PJM Interconnection, LLC",
                        "fueltype": "NG",
                        "value": "18542",
                        "value-units": "megawatthours",
                    }
                ]
            }
        },
    }
    drafts = provider.normalize(raw)
    assert len(drafts) == 1
    assert drafts[0].source_type == DataClassification.PUBLIC
    assert drafts[0].category == "POWER_BURN"
    assert drafts[0].geography == "PJM"
    assert drafts[0].value == 18542.0
    assert drafts[0].observation_time == datetime(2026, 8, 25, 14, tzinfo=timezone.utc)


def test_iso_rto_normalize_skips_missing_values():
    provider = ISORTOProvider(api_key="fake-key")
    raw = {"respondent": "CISO", "raw": {"response": {"data": [{"period": "2026-08-25T14"}]}}}
    assert provider.normalize(raw) == []


def test_iso_rto_normalize_demand_produces_public_demand_observations():
    provider = ISORTOProvider(api_key="fake-key")
    raw = {
        "respondent": "ERCO",
        "raw": {
            "response": {
                "data": [
                    {
                        "period": "2026-08-25T14",
                        "respondent-name": "ERCOT",
                        "value": "45210",
                        "value-units": "megawatthours",
                    }
                ]
            }
        },
    }
    drafts = provider._normalize_demand(raw)
    assert len(drafts) == 1
    assert drafts[0].category == "POWER"
    assert drafts[0].sub_category == "RTO_ELECTRICITY_DEMAND"
    assert drafts[0].geography == "ERCO"
    assert drafts[0].value == 45210.0
    assert drafts[0].license_type == "PUBLIC_DOMAIN_GOVERNMENT_DATA"


def test_iso_rto_normalize_demand_skips_missing_values():
    provider = ISORTOProvider(api_key="fake-key")
    raw = {"respondent": "MISO", "raw": {"response": {"data": [{"period": "2026-08-25T14"}]}}}
    assert provider._normalize_demand(raw) == []


@pytest.mark.asyncio
async def test_iso_rto_fetch_returns_nothing_without_api_key():
    provider = ISORTOProvider(api_key=None)
    result = await provider.fetch(FetchRequest())
    assert result == []
    health = await provider.health_check()
    assert health.status == "not_configured"


@pytest.mark.asyncio
async def test_iso_rto_fetch_calls_both_generation_and_demand_routes():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if "region-data" in request.url.path:
            return httpx.Response(
                200, json={"response": {"data": [{"period": "2026-08-25T14", "value": "1000"}]}}
            )
        return httpx.Response(200, json={"response": {"data": [{"period": "2026-08-25T14", "value": "500"}]}})

    transport = httpx.MockTransport(handler)
    provider = ISORTOProvider(api_key="fake-key", client=httpx.AsyncClient(transport=transport))
    drafts = await provider.fetch(FetchRequest(extra={"respondents": ["PJM"]}))

    assert any("fuel-type-data" in c for c in calls)
    assert any("region-data" in c for c in calls)
    assert any(d.sub_category == "RTO_NATURAL_GAS_GENERATION" for d in drafts)
    assert any(d.sub_category == "RTO_ELECTRICITY_DEMAND" for d in drafts)


def test_sec_edgar_normalize_produces_corporate_filing_observations():
    provider = SECEdgarProvider(contact_email="test@example.com")
    raw = {
        "cik": "0000895729",
        "raw": {
            "name": "Cheniere Energy, Inc.",
            "filings": {
                "recent": {
                    "form": ["8-K", "4", "10-Q"],
                    "filingDate": ["2026-08-20", "2026-08-19", "2026-08-01"],
                    "accessionNumber": ["0000895729-26-000123", "0000895729-26-000122", "0000895729-26-000100"],
                    "primaryDocument": ["form8k.htm", "form4.xml", "form10q.htm"],
                }
            },
        },
    }
    drafts = provider.normalize(raw)
    # form "4" is filtered out -- only 8-K and 10-Q are relevant filing types
    assert len(drafts) == 2
    assert {d.sub_category for d in drafts} == {"8-K", "10-Q"}
    assert all(d.source_type == DataClassification.PUBLIC for d in drafts)
    assert all(d.category == "CORPORATE_FILING" for d in drafts)
    eight_k = next(d for d in drafts if d.sub_category == "8-K")
    assert eight_k.metadata["company_name"] == "Cheniere Energy, Inc."
    assert "0000895729-26-000123" in eight_k.metadata["accession_number"]
    assert eight_k.observation_time == datetime(2026, 8, 20, tzinfo=timezone.utc)
    assert eight_k.license_type == "PUBLIC_DOMAIN_GOVERNMENT_DATA"
    assert eight_k.redistribution_allowed is True


def test_sec_edgar_provider_declares_licensing_metadata_class_attributes():
    provider = SECEdgarProvider(contact_email="test@example.com")
    assert provider.license_type == "PUBLIC_DOMAIN_GOVERNMENT_DATA"
    assert provider.public_or_commercial == "PUBLIC"
    assert provider.redistribution_allowed is True
    assert provider.ai_processing_allowed is True


def test_mock_cme_provider_leaves_licensing_metadata_unknown():
    # SIMULATED data has no real-world license to declare -- `None` (unknown), never
    # defaulted to permissive.
    provider = MockCMEProvider(seed=1)
    assert provider.license_type is None
    assert provider.redistribution_allowed is None


def test_sec_edgar_normalize_skips_irrelevant_forms_and_missing_dates():
    provider = SECEdgarProvider(contact_email="test@example.com")
    raw = {
        "cik": "0000033213",
        "raw": {
            "filings": {
                "recent": {
                    "form": ["3", "8-K"],
                    "filingDate": ["2026-08-01", None],
                    "accessionNumber": ["x", "y"],
                    "primaryDocument": ["a.xml", "b.htm"],
                }
            }
        },
    }
    assert provider.normalize(raw) == []


@pytest.mark.asyncio
async def test_sec_edgar_health_check_is_always_healthy_no_key_required():
    provider = SECEdgarProvider(contact_email=None)
    health = await provider.health_check()
    assert health.status == "healthy"


@pytest.mark.asyncio
async def test_mock_cme_produces_36_contracts_marked_simulated():
    provider = MockCMEProvider(seed=1)
    drafts = await provider.fetch(FetchRequest(end=datetime(2026, 8, 25, tzinfo=timezone.utc)))
    assert len(drafts) == 36
    assert all(d.source_type == DataClassification.SIMULATED for d in drafts)
    assert all(d.value > 0 for d in drafts)


@pytest.mark.asyncio
async def test_mock_cme_is_deterministic_for_same_seed():
    a = await MockCMEProvider(seed=7).fetch(FetchRequest(end=datetime(2026, 8, 25, tzinfo=timezone.utc)))
    b = await MockCMEProvider(seed=7).fetch(FetchRequest(end=datetime(2026, 8, 25, tzinfo=timezone.utc)))
    assert [d.value for d in a] == [d.value for d in b]


@pytest.mark.asyncio
async def test_mock_ice_produces_ttf_price():
    provider = MockICEProvider(seed=1)
    drafts = await provider.fetch(FetchRequest(end=datetime(2026, 8, 25, tzinfo=timezone.utc)))
    assert len(drafts) == 1
    assert drafts[0].symbol == "TTF"
    assert drafts[0].source_type == DataClassification.SIMULATED


@pytest.mark.asyncio
async def test_mock_news_produces_labeled_simulated_headlines():
    provider = MockNewsProvider()
    drafts = await provider.fetch(FetchRequest(end=datetime.now(timezone.utc)))
    assert len(drafts) == 5
    assert all(d.source_type == DataClassification.SIMULATED for d in drafts)
    assert all("headline" in d.metadata for d in drafts)


def test_registry_every_provider_has_classification():
    registry = build_default_registry()
    for provider in registry.all():
        assert provider.classification in DataClassification


@pytest.mark.asyncio
async def test_registry_health_snapshot_reports_unconfigured_stubs():
    registry = build_default_registry()
    health = await registry.health_snapshot()
    statuses = {h.provider_id: h.status for h in health}
    assert statuses["ferc_public"] == "not_configured"
    assert statuses["mock_cme"] == "healthy"
    # iso_rto_public shares EIA_API_KEY with the eia provider -- neither is configured
    # in the test environment, so both honestly report the same not_configured status.
    assert statuses["iso_rto_public"] == "not_configured"
    # sec_edgar needs no API key at all -- it's real and healthy without any config.
    assert statuses["sec_edgar"] == "healthy"
    # nhc_tropical (NHC CurrentStorms.json) also needs no API key.
    assert statuses["nhc_tropical"] == "healthy"
