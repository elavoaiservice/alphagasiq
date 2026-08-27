"""Repository round-trip for the Overnight Intelligence Brief
(docs/alpha-intelligence.md section 10, Milestone 7)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from db import SqlAppRepository
from schemas import IntelligenceBrief, Signal, SignalDirection, SignalType


def make_brief(**overrides) -> IntelligenceBrief:
    defaults = dict(
        market="HENRY_HUB",
        period_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        period_end=datetime(2026, 1, 2, tzinfo=timezone.utc),
        headline="Test headline",
        summary="Test summary",
    )
    defaults.update(overrides)
    return IntelligenceBrief(**defaults)


@pytest.fixture
async def repo():
    r = SqlAppRepository("sqlite+aiosqlite:///:memory:")
    await r.init_schema()
    yield r
    await r.dispose()


async def test_save_and_get_round_trips_embedded_signals(repo):
    sig = Signal(
        signal_type=SignalType.WEATHER_CHANGE,
        category="WEATHER",
        headline="Cold snap",
        description="d",
        materiality_score=75,
        confidence=0.8,
        direction=SignalDirection.BULLISH,
    )
    brief = make_brief(top_signals=[sig])
    await repo.save_intelligence_brief(brief)

    got = await repo.get_intelligence_brief(str(brief.id))
    assert got is not None
    assert got["headline"] == "Test headline"
    assert len(got["top_signals"]) == 1
    assert got["top_signals"][0]["headline"] == "Cold snap"


async def test_get_unknown_brief_returns_none(repo):
    assert await repo.get_intelligence_brief("00000000-0000-0000-0000-000000000000") is None


async def test_list_is_most_recent_first_and_respects_limit(repo):
    for i in range(3):
        await repo.save_intelligence_brief(make_brief(headline=f"brief-{i}"))

    listed = await repo.list_intelligence_briefs(limit=2)
    assert len(listed) == 2
    assert listed[0]["headline"] == "brief-2"


async def test_list_filters_by_market(repo):
    await repo.save_intelligence_brief(make_brief(market="HENRY_HUB"))
    await repo.save_intelligence_brief(make_brief(market="TTF"))

    listed = await repo.list_intelligence_briefs(market="TTF")
    assert len(listed) == 1
    assert listed[0]["market"] == "TTF"


async def test_organization_scoped_brief_is_isolated_from_other_orgs(repo):
    await repo.save_intelligence_brief(make_brief(organization_id="org-a"))
    await repo.save_intelligence_brief(make_brief(organization_id=None))

    listed = await repo.list_intelligence_briefs(organization_id="org-b")
    # org-b sees only the platform-wide (organization_id=None) brief, not org-a's.
    assert len(listed) == 1
    assert listed[0]["organization_id"] is None
