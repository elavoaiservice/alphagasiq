"""The real ICE Dutch TTF connector (`providers/ice_yahoo.py`).

The unit conversion is the whole point of this connector, so it is tested
directly and against a hand-computed value. Every network call is stubbed --
these tests must never hit Yahoo.
"""
from __future__ import annotations

import pytest

from data_sdk import FetchRequest
from data_service.providers.ice_yahoo import (
    MMBTU_PER_MWH,
    YahooTTFProvider,
    eur_mwh_to_usd_mmbtu,
)


# ── the conversion ────────────────────────────────────────────────────────────

def test_conversion_matches_a_hand_computed_value():
    # 78.965 EUR/MWh x 1.1633 USD/EUR = 91.862... USD/MWh
    # 91.862... / 3.412142 MMBtu/MWh   = 26.922... USD/MMBtu
    assert round(eur_mwh_to_usd_mmbtu(78.965, 1.1633), 3) == 26.922


def test_conversion_constant_is_the_real_energy_equivalence():
    # 1 kWh = 3412.142 BTU  ->  1 MWh = 3.412142 MMBtu.
    assert MMBTU_PER_MWH == pytest.approx(3.412142)


def test_conversion_is_linear_in_both_inputs():
    base = eur_mwh_to_usd_mmbtu(50.0, 1.10)
    assert eur_mwh_to_usd_mmbtu(100.0, 1.10) == pytest.approx(base * 2)
    assert eur_mwh_to_usd_mmbtu(50.0, 2.20) == pytest.approx(base * 2)


# ── fetch behaviour ───────────────────────────────────────────────────────────

def _provider(quotes):
    """A provider whose _quote returns from `quotes` ({symbol: (px, ccy) | exc})."""
    p = YahooTTFProvider()

    async def _quote(symbol, _client):
        v = quotes.get(symbol)
        if isinstance(v, Exception):
            raise v
        return v

    p._quote = _quote  # type: ignore[method-assign]
    return p


@pytest.mark.asyncio
async def test_fetch_converts_and_records_full_provenance():
    p = _provider({"TTF=F": (78.965, "EUR"), "EURUSD=X": (1.1633, "USD")})
    drafts = await p.fetch(FetchRequest())

    assert len(drafts) == 1
    d = drafts[0]
    assert d.value == 26.922
    assert d.unit == "USD_MMBTU"
    assert d.symbol == "TTF"
    # The published number must be re-derivable from the recorded inputs.
    assert d.metadata["raw_price"] == 78.965
    assert d.metadata["raw_unit"] == "EUR_MWH"
    assert d.metadata["fx_rate_usd_per_eur"] == 1.1633
    assert round(
        (d.metadata["raw_price"] * d.metadata["fx_rate_usd_per_eur"]) / d.metadata["mmbtu_per_mwh"], 3
    ) == d.value


@pytest.mark.asyncio
async def test_missing_fx_publishes_nothing_rather_than_a_wrong_number():
    """A TTF price with a guessed rate would be labelled real and be wrong --
    the connector must stay silent instead."""
    p = _provider({"TTF=F": (78.965, "EUR"), "EURUSD=X": None})
    assert await p.fetch(FetchRequest()) == []


@pytest.mark.asyncio
async def test_missing_ttf_publishes_nothing():
    p = _provider({"TTF=F": None, "EURUSD=X": (1.1633, "USD")})
    assert await p.fetch(FetchRequest()) == []


@pytest.mark.asyncio
async def test_network_failure_degrades_to_empty_never_raises():
    """Same contract as YahooHenryHubProvider: a fetch failure must not break boot."""
    p = _provider({"TTF=F": RuntimeError("boom"), "EURUSD=X": (1.1633, "USD")})
    assert await p.fetch(FetchRequest()) == []


@pytest.mark.asyncio
async def test_unexpected_quote_currency_publishes_nothing():
    """If Yahoo ever quotes TTF in something other than EUR/MWh, the conversion
    would be silently wrong — refuse rather than guess."""
    p = _provider({"TTF=F": (78.965, "USD"), "EURUSD=X": (1.1633, "USD")})
    assert await p.fetch(FetchRequest()) == []


@pytest.mark.asyncio
async def test_health_is_degraded_when_only_one_leg_answers():
    p = _provider({"TTF=F": (78.965, "EUR"), "EURUSD=X": None})
    assert (await p.health_check()).status == "degraded"


@pytest.mark.asyncio
async def test_health_is_healthy_when_both_legs_answer():
    p = _provider({"TTF=F": (78.965, "EUR"), "EURUSD=X": (1.1633, "USD")})
    assert (await p.health_check()).status == "healthy"
