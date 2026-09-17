"""Providers must reuse one pooled HTTP client, not open a pool per fetch.

This is the bug that took the production host down on 2026-09-17. Every connector
did `async with (self._client or httpx.AsyncClient()) as client:`, opening a fresh
connection pool per fetch and closing it at the end. At MARKET_REFRESH_SECONDS=10
each poll's TCP connections sat in TIME_WAIT for ~30s and accumulated to 21,302
sockets against an ephemeral port range of 16,384 — the machine could no longer open
any outbound connection, the public site 502'd, and Colima could not reach its own VM.
"""
from __future__ import annotations

import httpx
import pytest

from data_sdk import FetchRequest
from data_service.providers.cme_yahoo import YahooHenryHubProvider
from data_service.providers.ice_yahoo import YahooTTFProvider


def _transport(payload):
    return httpx.MockTransport(lambda request: httpx.Response(200, json=payload))


_QUOTE = {"chart": {"result": [{"meta": {"regularMarketPrice": 3.21, "currency": "USD"}}]}}
_TTF = {"chart": {"result": [{"meta": {"regularMarketPrice": 80.0, "currency": "EUR"}}]}}


@pytest.mark.asyncio
async def test_the_same_client_is_reused_across_fetches():
    p = YahooHenryHubProvider()
    first = p.http_client()
    second = p.http_client()
    assert first is second, "a new client per call defeats connection reuse"
    await p.aclose()


@pytest.mark.asyncio
async def test_fetch_does_not_close_the_pooled_client():
    """The core regression: closing per fetch is what leaked sockets."""
    p = YahooHenryHubProvider()
    p.http_client()  # materialise it
    await p.fetch(FetchRequest(extra={"n_contracts": 1}))
    assert p._owned_http_client is not None
    assert not p._owned_http_client.is_closed, "client was closed by fetch — sockets will leak"
    await p.aclose()


@pytest.mark.asyncio
async def test_an_injected_client_is_never_closed_by_a_fetch():
    """Second latent bug in the old pattern: `async with` closed a caller-supplied
    client, so a second fetch on the same instance used a closed one."""
    injected = httpx.AsyncClient(transport=_transport(_QUOTE))
    p = YahooHenryHubProvider(client=injected)

    await p.fetch(FetchRequest(extra={"n_contracts": 1}))
    assert not injected.is_closed

    # And a second fetch still works rather than raising on a closed client.
    drafts = await p.fetch(FetchRequest(extra={"n_contracts": 1}))
    assert drafts
    await injected.aclose()


@pytest.mark.asyncio
async def test_ttf_provider_reuses_its_client_too():
    injected = httpx.AsyncClient(transport=_transport(_TTF))
    p = YahooTTFProvider(client=injected)
    await p.fetch(FetchRequest())
    assert not injected.is_closed
    assert await p.fetch(FetchRequest()) is not None
    await injected.aclose()


@pytest.mark.asyncio
async def test_pool_is_bounded():
    """An unbounded pool would trade one resource leak for another."""
    p = YahooHenryHubProvider()
    client = p.http_client()
    # httpx keeps the limits on the transport's connection pool.
    pool = client._transport._pool  # type: ignore[attr-defined]
    assert pool._max_connections == 20
    assert pool._max_keepalive_connections == 10
    await p.aclose()


@pytest.mark.asyncio
async def test_aclose_is_idempotent_and_reopens_on_demand():
    p = YahooHenryHubProvider()
    p.http_client()
    await p.aclose()
    await p.aclose()  # must not raise
    assert p.http_client() is not None  # usable again after close
    await p.aclose()
