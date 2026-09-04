"""Repository round-trips for the Enterprise Data Platform
(docs/alpha-intelligence.md section 11, Milestone 8): workspaces, enterprise
data sources, datasets, entitlements, records, and events."""

from __future__ import annotations

import pytest
from db import SqlAppRepository
from schemas import (
    EnterpriseConnectorType,
    EnterpriseDataClassification,
    EnterpriseDataDomain,
    EnterpriseDataEntitlement,
    EnterpriseDataset,
    EnterpriseDataSource,
    EnterpriseEntitlementPrincipalType,
    Workspace,
)


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


async def test_save_and_list_workspace(repo, org_id):
    ws = Workspace(organization_id=org_id, name="Trading Desk", created_by="u-1")
    await repo.save_workspace(ws)

    listed = await repo.list_workspaces(organization_id=org_id)
    assert len(listed) == 1
    assert listed[0]["name"] == "Trading Desk"

    got = await repo.get_workspace(str(ws.id))
    assert got is not None and got["id"] == str(ws.id)


async def test_update_and_delete_workspace(repo, org_id):
    ws = Workspace(organization_id=org_id, name="Trading Desk")
    await repo.save_workspace(ws)

    updated = await repo.update_workspace(str(ws.id), name="Renamed Desk")
    assert updated["name"] == "Renamed Desk"

    assert await repo.update_workspace("nonexistent", name="x") is None

    assert await repo.delete_workspace(str(ws.id)) is True
    assert await repo.get_workspace(str(ws.id)) is None
    assert await repo.delete_workspace(str(ws.id)) is False


async def test_workspace_membership_add_list_remove(repo, org_id):
    ws = Workspace(organization_id=org_id, name="Trading Desk")
    await repo.save_workspace(ws)

    await repo.add_workspace_member(str(ws.id), "u-1", added_by="u-admin")
    # Adding the same member twice is a no-op, not a duplicate row.
    await repo.add_workspace_member(str(ws.id), "u-1", added_by="u-admin")

    members = await repo.list_workspace_members(str(ws.id))
    assert len(members) == 1
    assert members[0]["user_id"] == "u-1"

    assert await repo.remove_workspace_member(str(ws.id), "u-1") is True
    assert await repo.list_workspace_members(str(ws.id)) == []
    assert await repo.remove_workspace_member(str(ws.id), "u-1") is False


async def test_save_and_list_enterprise_data_source(repo, org_id):
    source = EnterpriseDataSource(
        organization_id=org_id,
        name="Well CSV",
        connector_type=EnterpriseConnectorType.MANUAL_UPLOAD,
        classification=EnterpriseDataClassification.CUSTOMER_CONFIDENTIAL,
    )
    await repo.save_enterprise_data_source(source)

    listed = await repo.list_enterprise_data_sources(organization_id=org_id)
    assert len(listed) == 1
    assert listed[0]["status"] == "DRAFT"

    got = await repo.get_enterprise_data_source(str(source.id))
    assert got["connector_type"] == "MANUAL_UPLOAD"


async def test_update_and_delete_enterprise_data_source(repo, org_id):
    source = EnterpriseDataSource(
        organization_id=org_id,
        name="Well CSV",
        connector_type=EnterpriseConnectorType.MANUAL_UPLOAD,
        classification=EnterpriseDataClassification.CUSTOMER_CONFIDENTIAL,
    )
    await repo.save_enterprise_data_source(source)

    updated = await repo.update_enterprise_data_source(str(source.id), status="ACTIVE")
    assert updated["status"] == "ACTIVE"
    assert updated["updated_at"] >= source.updated_at.replace(tzinfo=None)

    assert await repo.delete_enterprise_data_source(str(source.id)) is True
    assert await repo.get_enterprise_data_source(str(source.id)) is None


async def test_dataset_lifecycle_schema_sync_and_records(repo, org_id):
    source = EnterpriseDataSource(
        organization_id=org_id,
        name="Well CSV",
        connector_type=EnterpriseConnectorType.MANUAL_UPLOAD,
        classification=EnterpriseDataClassification.CUSTOMER_CONFIDENTIAL,
    )
    await repo.save_enterprise_data_source(source)

    dataset = EnterpriseDataset(
        source_id=source.id,
        organization_id=org_id,
        name="Well Production",
        domain=EnterpriseDataDomain.PRODUCTION,
        classification=EnterpriseDataClassification.CUSTOMER_CONFIDENTIAL,
    )
    await repo.save_enterprise_dataset(dataset)

    listed = await repo.list_enterprise_datasets(source_id=str(source.id))
    assert len(listed) == 1
    assert listed[0]["row_count"] == 0
    assert listed[0]["last_synced_at"] is None

    n = await repo.save_enterprise_records(str(dataset.id), [{"well_id": "W-1"}, {"well_id": "W-2"}])
    assert n == 2

    records = await repo.list_enterprise_records(str(dataset.id))
    assert len(records) == 2

    updated = await repo.update_enterprise_dataset_sync(
        str(dataset.id), schema_summary={"well_id": "string"}, row_count=2
    )
    assert updated["row_count"] == 2
    assert updated["last_synced_at"] is not None
    assert updated["schema_summary"] == {"well_id": "string"}


async def test_entitlement_grant_list_revoke(repo, org_id):
    source = EnterpriseDataSource(
        organization_id=org_id,
        name="Well CSV",
        connector_type=EnterpriseConnectorType.MANUAL_UPLOAD,
        classification=EnterpriseDataClassification.CUSTOMER_CONFIDENTIAL,
    )
    await repo.save_enterprise_data_source(source)
    dataset = EnterpriseDataset(
        source_id=source.id,
        organization_id=org_id,
        name="Well Production",
        domain=EnterpriseDataDomain.PRODUCTION,
        classification=EnterpriseDataClassification.CUSTOMER_CONFIDENTIAL,
    )
    await repo.save_enterprise_dataset(dataset)

    ent = EnterpriseDataEntitlement(
        dataset_id=dataset.id, principal_type=EnterpriseEntitlementPrincipalType.AGENT, principal_id="WEATHER"
    )
    await repo.save_enterprise_data_entitlement(ent)

    listed = await repo.list_enterprise_data_entitlements(str(dataset.id))
    assert len(listed) == 1
    assert listed[0]["principal_type"] == "AGENT"

    assert await repo.delete_enterprise_data_entitlement(str(ent.id)) is True
    assert await repo.list_enterprise_data_entitlements(str(dataset.id)) == []
    assert await repo.delete_enterprise_data_entitlement(str(ent.id)) is False


async def test_event_recording_and_listing(repo, org_id):
    source = EnterpriseDataSource(
        organization_id=org_id,
        name="Well CSV",
        connector_type=EnterpriseConnectorType.MANUAL_UPLOAD,
        classification=EnterpriseDataClassification.CUSTOMER_CONFIDENTIAL,
    )
    await repo.save_enterprise_data_source(source)

    event = await repo.record_enterprise_data_event(
        source_id=str(source.id), event_type="test_connection", status="success", detail="ok", latency_ms=12.5
    )
    assert event["status"] == "success"

    events = await repo.list_enterprise_data_events(str(source.id))
    assert len(events) == 1
    assert events[0]["event_type"] == "test_connection"
