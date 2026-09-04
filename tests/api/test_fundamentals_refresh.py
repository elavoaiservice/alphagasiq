"""Phase 1 free-data-feed integration (docs/data-sources.md):
`AppState.refresh_fundamentals_from_public_data()` -- proves it prefers real EIA
storage history when configured, and leaves the existing (synthetic-seed or
previously-real) baseline untouched when EIA isn't configured, rather than
blending or silently overwriting with a partial result."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from data_sdk import FetchRequest, ProviderHealth
from schemas import DataClassification, Lineage, ObservationDraft


class _FakeEIAProvider:
    provider_id = "eia"
    classification = DataClassification.PUBLIC
    freshness_sla_seconds = 7 * 24 * 3600

    def __init__(self, storage_values: list[float]):
        self._storage_values = storage_values

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(provider_id=self.provider_id, status="healthy")

    async def fetch(self, request: FetchRequest) -> list[ObservationDraft]:
        if request.series_ids == ["EIA.NG.STORAGE.LOWER48"]:
            now = datetime.now(timezone.utc)
            return [
                ObservationDraft(
                    source="EIA",
                    source_type=DataClassification.PUBLIC,
                    series_id="EIA.NG.STORAGE.LOWER48",
                    category="STORAGE",
                    value=value,
                    unit="BCF",
                    observation_time=now - timedelta(weeks=i),
                    publication_time=now,
                    lineage=Lineage(),
                )
                for i, value in enumerate(self._storage_values)
            ]
        return []


class _FailingEIAProvider(_FakeEIAProvider):
    async def fetch(self, request: FetchRequest) -> list[ObservationDraft]:
        raise RuntimeError("simulated EIA outage")


class _FakeNOAAProvider:
    """Stands in for the real `NOAAProvider` in every test in this file -- the real
    one makes actual HTTP calls to api.weather.gov even with no API key configured
    (NOAA needs none), which this sandbox's network proxy blocks outbound, and which
    a unit test must never depend on regardless of environment (docs/data-sources.md
    section 34: mocks/fixtures, not live public APIs, in automated tests)."""

    provider_id = "noaa_nws"
    classification = DataClassification.PUBLIC
    freshness_sla_seconds = 6 * 3600

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(provider_id=self.provider_id, status="healthy")

    async def fetch(self, request: FetchRequest) -> list[ObservationDraft]:
        now = datetime.now(timezone.utc)
        return [
            ObservationDraft(
                source="NOAA_NWS",
                source_type=DataClassification.PUBLIC,
                series_id="NOAA.HDD_CDD.NATIONAL_APPROXIMATION",
                category="WEATHER",
                sub_category="NATIONAL_HDD_CDD_UNWEIGHTED_APPROXIMATION",
                geography="US_NATIONAL",
                value=12.0,
                unit="HDD",
                observation_time=now,
                publication_time=now,
                metadata={"hdd": 12.0, "cdd": 0.0},
                lineage=Lineage(),
            )
        ]


@pytest.fixture
async def state():
    from api_app import state as state_module

    state_module.reset_app_state()
    app_state = await state_module.get_app_state()
    app_state.providers.register(_FakeNOAAProvider())
    yield app_state
    state_module.reset_app_state()


async def test_refresh_leaves_baseline_untouched_when_eia_not_configured(state):
    # The default test environment has no EIA_API_KEY configured -- the registered
    # "eia" provider already reports not_configured.
    baseline_before = dict(state.storage_baseline)
    weather_before = dict(state.weather_kwargs)

    summary = await state.refresh_fundamentals_from_public_data()

    assert summary["eia_configured"] is False
    assert summary["storage_updated"] is False
    assert state.storage_baseline == baseline_before
    assert state.storage_baseline_classification == "SIMULATED"
    # NOAA needs no API key, so weather does update even when EIA doesn't.
    assert state.weather_kwargs != weather_before or summary["weather_updated"] is False


async def test_refresh_updates_storage_baseline_from_real_eia_history(state):
    state.providers.register(_FakeEIAProvider(storage_values=[3200.0, 3100.0, 3050.0, 2900.0]))

    summary = await state.refresh_fundamentals_from_public_data()

    assert summary["eia_configured"] is True
    assert summary["storage_updated"] is True
    assert state.storage_baseline_classification == "PUBLIC"
    assert state.storage_baseline["current_inventory_bcf"] == 3200.0  # most recent (i=0)
    assert state.storage_baseline["five_year_low_bcf"] == 2900.0
    assert state.storage_baseline["five_year_high_bcf"] == 3200.0


async def test_refresh_does_not_update_baseline_with_insufficient_history(state):
    state.providers.register(_FakeEIAProvider(storage_values=[3200.0]))  # only 1 observation
    baseline_before = dict(state.storage_baseline)

    summary = await state.refresh_fundamentals_from_public_data()

    assert summary["storage_updated"] is False
    assert state.storage_baseline == baseline_before
    assert state.storage_baseline_classification == "SIMULATED"


async def test_refresh_survives_eia_fetch_failure_without_raising(state):
    state.providers.register(_FailingEIAProvider(storage_values=[]))
    baseline_before = dict(state.storage_baseline)

    summary = await state.refresh_fundamentals_from_public_data()  # must not raise

    assert summary["storage_updated"] is False
    assert state.storage_baseline == baseline_before


async def test_refresh_updates_weather_kwargs_from_real_noaa_data(state):
    weather_before = dict(state.weather_kwargs)
    assert weather_before["model"] == "SIMULATED_FALLBACK"

    summary = await state.refresh_fundamentals_from_public_data()

    assert summary["weather_updated"] is True
    assert state.weather_kwargs["model"] == "NOAA_NWS_FORECAST"
    # First real refresh: comparison equals the run itself (no prior real snapshot).
    assert state.weather_kwargs["hdd_comparison"] == state.weather_kwargs["hdd_run"]
