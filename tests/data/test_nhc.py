import httpx
import pytest
from data_service.providers.nhc import NHC_CURRENT_STORMS_URL, TropicalWeatherConnector, _has_potential_gulf_exposure
from data_sdk import FetchRequest
from schemas import DataClassification


def test_gulf_exposure_true_inside_bounding_box():
    assert _has_potential_gulf_exposure(25.0, -90.0) is True


def test_gulf_exposure_false_outside_bounding_box():
    assert _has_potential_gulf_exposure(40.0, -70.0) is False


def test_gulf_exposure_none_when_position_unknown():
    assert _has_potential_gulf_exposure(None, -90.0) is None
    assert _has_potential_gulf_exposure(25.0, None) is None


def test_normalize_produces_public_observation_with_gulf_exposure():
    provider = TropicalWeatherConnector()
    raw = {
        "activeStorms": [
            {
                "id": "AL052026",
                "name": "Storm Example",
                "classification": "HU",
                "latitude": 24.5,
                "longitude": -89.0,
                "intensity": 90,
                "pressure": 970,
                "basin": "AL",
                "movementDir": 300,
                "movementSpeed": 12,
            }
        ]
    }
    drafts = provider.normalize(raw)
    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.source == "NOAA_NHC"
    assert draft.source_type == DataClassification.PUBLIC
    assert draft.series_id == "NHC.STORM.AL052026"
    assert draft.category == "TROPICAL_WEATHER"
    assert draft.sub_category == "HURRICANE"
    assert draft.geography == "GULF_OF_MEXICO"
    assert draft.value == 90.0
    assert draft.metadata["potential_gulf_exposure"] is True
    assert draft.license_type == "PUBLIC_DOMAIN_GOVERNMENT_DATA"
    assert draft.redistribution_allowed is True


def test_normalize_uses_basin_when_no_gulf_exposure():
    provider = TropicalWeatherConnector()
    raw = {
        "activeStorms": [
            {
                "id": "EP012026",
                "name": "Storm Far Away",
                "classification": "TS",
                "latitude": 15.0,
                "longitude": -140.0,
                "intensity": 45,
                "basin": "EP",
            }
        ]
    }
    drafts = provider.normalize(raw)
    assert drafts[0].geography == "EP"
    assert drafts[0].sub_category == "TROPICAL_STORM"
    assert drafts[0].metadata["potential_gulf_exposure"] is False


def test_normalize_passes_through_unrecognized_classification_code():
    provider = TropicalWeatherConnector()
    raw = {"activeStorms": [{"id": "X1", "name": "Mystery", "classification": "ZZ", "intensity": 30}]}
    drafts = provider.normalize(raw)
    assert drafts[0].sub_category == "ZZ"


def test_normalize_skips_storms_missing_required_fields():
    provider = TropicalWeatherConnector()
    raw = {
        "activeStorms": [
            {"id": "AL01", "classification": "HU"},  # missing name
            {"name": "No ID", "classification": "TS"},  # missing id
            {"id": "AL02", "name": "No Classification"},  # missing classification
        ]
    }
    assert provider.normalize(raw) == []


def test_normalize_handles_no_active_storms():
    provider = TropicalWeatherConnector()
    assert provider.normalize({"activeStorms": []}) == []
    assert provider.normalize({}) == []


@pytest.mark.asyncio
async def test_fetch_success_via_mock_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == NHC_CURRENT_STORMS_URL
        return httpx.Response(
            200,
            json={
                "activeStorms": [
                    {"id": "AL01", "name": "Test", "classification": "TD", "intensity": 30, "basin": "AL"}
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    provider = TropicalWeatherConnector(client=httpx.AsyncClient(transport=transport))
    drafts = await provider.fetch(FetchRequest())
    assert len(drafts) == 1
    assert drafts[0].sub_category == "TROPICAL_DEPRESSION"


@pytest.mark.asyncio
async def test_fetch_raises_on_http_error():
    transport = httpx.MockTransport(lambda request: httpx.Response(503, json={"error": "unavailable"}))
    provider = TropicalWeatherConnector(client=httpx.AsyncClient(transport=transport))
    with pytest.raises(httpx.HTTPStatusError):
        await provider.fetch(FetchRequest())


@pytest.mark.asyncio
async def test_health_check_always_healthy_no_api_key_required():
    provider = TropicalWeatherConnector()
    health = await provider.health_check()
    assert health.status == "healthy"
    assert health.provider_id == "nhc_tropical"
