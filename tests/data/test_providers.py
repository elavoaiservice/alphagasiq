import asyncio
from datetime import datetime, timezone

import pytest
from data_service.providers.eia import EIAProvider
from data_service.providers.mock_market_data import MockCMEProvider, MockICEProvider
from data_service.providers.mock_news import MockNewsProvider
from data_service.providers.noaa import NOAAProvider, degree_days
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
