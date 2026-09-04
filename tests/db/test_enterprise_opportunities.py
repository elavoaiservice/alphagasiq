"""Repository round-trips for the Enterprise Opportunity Engine
(docs/alpha-intelligence.md section 11.7, Milestone 10)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from db import SqlAppRepository
from schemas import EnterpriseOpportunity, EnterpriseOpportunityType


@pytest.fixture
async def repo():
    r = SqlAppRepository("sqlite+aiosqlite:///:memory:")
    await r.init_schema()
    yield r
    await r.dispose()


@pytest.fixture
async def org_id(repo):
    org = await repo.create_organization(name="Acme Energy")
    return org["id"]


def _opportunity(**overrides) -> EnterpriseOpportunity:
    defaults = dict(
        organization_id="org-a",
        opportunity_type=EnterpriseOpportunityType.HEDGE_MISALIGNED_POSITION,
        market="HENRY_HUB",
        title="t",
        summary="s",
        confidence=0.7,
    )
    defaults.update(overrides)
    return EnterpriseOpportunity(**defaults)


async def test_save_and_list_by_organization(repo, org_id):
    await repo.save_enterprise_opportunity(_opportunity(organization_id=org_id))
    await repo.save_enterprise_opportunity(_opportunity(organization_id="org-b"))

    listed = await repo.list_enterprise_opportunities(organization_id=org_id)
    assert len(listed) == 1
    assert listed[0]["organization_id"] == org_id


async def test_list_filters_by_status(repo, org_id):
    opp = _opportunity(organization_id=org_id)
    await repo.save_enterprise_opportunity(opp)

    assert await repo.list_enterprise_opportunities(organization_id=org_id, status="APPROVED") == []
    assert len(await repo.list_enterprise_opportunities(organization_id=org_id, status="PENDING")) == 1


async def test_get_by_id(repo, org_id):
    opp = _opportunity(organization_id=org_id)
    await repo.save_enterprise_opportunity(opp)

    got = await repo.get_enterprise_opportunity(str(opp.id))
    assert got is not None
    assert got["title"] == "t"
    assert got["status"] == "PENDING"

    assert await repo.get_enterprise_opportunity("00000000-0000-0000-0000-000000000000") is None


async def test_update_status_marks_reviewed(repo, org_id):
    opp = _opportunity(organization_id=org_id)
    await repo.save_enterprise_opportunity(opp)

    updated = await repo.update_enterprise_opportunity_status(
        str(opp.id), status="APPROVED", reviewed_by="u-1", reviewed_at=datetime.now(timezone.utc)
    )
    assert updated is not None
    assert updated["status"] == "APPROVED"
    assert updated["reviewed_by"] == "u-1"
    assert updated["reviewed_at"] is not None


async def test_update_status_unknown_id_returns_none(repo):
    result = await repo.update_enterprise_opportunity_status(
        "00000000-0000-0000-0000-000000000000", status="APPROVED", reviewed_by="u-1", reviewed_at=datetime.now(timezone.utc)
    )
    assert result is None


async def test_supporting_signal_ids_round_trip(repo, org_id):
    opp = _opportunity(organization_id=org_id, supporting_signal_ids=["sig-1", "sig-2"])
    await repo.save_enterprise_opportunity(opp)

    got = await repo.get_enterprise_opportunity(str(opp.id))
    assert got["supporting_signal_ids"] == ["sig-1", "sig-2"]
