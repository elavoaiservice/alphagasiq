"""The NOAA gridpoint URL fix.

`REGION_STATIONS` mapped each region to a forecast office ("OKX") and the connector
requested `/gridpoints/OKX/forecast`. The NWS endpoint is
`/gridpoints/{office}/{gridX},{gridY}/forecast`, so that URL is a guaranteed 404 —
every NOAA fetch failed from the day the connector shipped (2,029 consecutive errors
in the deployed environment), and `weather_kwargs` was never updated from real data.

The connector now resolves the forecast URL through the documented
`/points/{lat},{lon}` lookup, which returns the exact URL to use.
"""
from __future__ import annotations

import pytest

from data_sdk import FetchRequest
from data_service.providers.noaa import REGION_POINTS, NOAAProvider


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Client:
    """Records every URL requested and answers /points and /gridpoints."""

    def __init__(self):
        self.urls: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kw):
        self.urls.append(url)
        if "/points/" in url:
            return _Resp({"properties": {"forecast": "https://api.weather.gov/gridpoints/OKX/33,42/forecast"}})
        if "/alerts/active" in url:
            return _Resp({"features": []})
        return _Resp({"properties": {"periods": [
            {"temperature": 40, "startTime": "2026-09-15T06:00:00-04:00"},
        ]}})


@pytest.mark.asyncio
async def test_forecast_url_comes_from_the_points_lookup_not_hand_built():
    client = _Client()
    p = NOAAProvider(contact_token="t", client=client)
    await p.fetch(FetchRequest(extra={"regions": ["NORTHEAST"]}))

    # The bug: an office code with no grid coordinates.
    assert not any(u.endswith("/gridpoints/OKX/forecast") for u in client.urls)
    assert any("/points/" in u for u in client.urls)
    assert any("gridpoints/OKX/33,42/forecast" in u for u in client.urls)


@pytest.mark.asyncio
async def test_the_points_lookup_is_cached_per_region():
    """One /points call per region per process, not one per fetch."""
    client = _Client()
    p = NOAAProvider(contact_token="t", client=client)

    await p.fetch(FetchRequest(extra={"regions": ["NORTHEAST"]}))
    await p.fetch(FetchRequest(extra={"regions": ["NORTHEAST"]}))

    assert len([u for u in client.urls if "/points/" in u]) == 1


@pytest.mark.asyncio
async def test_an_unknown_region_is_skipped_not_fatal():
    client = _Client()
    p = NOAAProvider(contact_token="t", client=client)
    drafts = await p.fetch(FetchRequest(extra={"regions": ["ATLANTIS"]}))
    assert not any("/points/" in u for u in client.urls)
    assert isinstance(drafts, list)


def test_us_national_is_derived_not_fetched():
    """It is computed by _national_degree_day_average from the other regions;
    fetching it re-read New York and mislabelled it as a national reading."""
    assert "US_NATIONAL" not in REGION_POINTS


def test_every_region_has_real_coordinates():
    for region, (lat, lon) in REGION_POINTS.items():
        assert -90 <= lat <= 90, region
        assert -180 <= lon <= 180, region
        # All four demand centres are in the continental US.
        assert 24 <= lat <= 50 and -125 <= lon <= -66, region
