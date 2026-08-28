"""Milestone 8 (docs/alpha-intelligence.md section 11.3/11.4): Enterprise Data
Platform admin surface -- register a source, run it through its connector's
`test_connection()`/`discover_schema()`/`preview()`/`ingest()`, register
datasets, and grant dataset entitlements. `EnterpriseDataSourceRow`
deliberately carries no credential/secret field -- exactly `DataFeedConfigRow`'s
existing posture. Every endpoint here is gated by `admin.enterprise_data`
(granted to ADMIN and SUPER_ADMIN).

All six `EnterpriseConnectorType` values are genuinely operable
(`enterprise_data_service.connector`): `MANUAL_UPLOAD` and `WEBHOOK` take rows
from the request body / the webhook staging buffer respectively, while
`REST_API`/`DATABASE`/`S3`/`SFTP` pull live from wherever the source's
`connection_config` points -- a connector missing its required configuration
(or its environment-provisioned credential) reports `not_configured` honestly
rather than silently behaving like `MANUAL_UPLOAD` or fabricating data.
"""

from __future__ import annotations

import os
import time
from typing import Any

from enterprise_data_service import build_connector
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from schemas import (
    EnterpriseConnectorType,
    EnterpriseDataClassification,
    EnterpriseDataDomain,
    EnterpriseDataEntitlement,
    EnterpriseDataset,
    EnterpriseDataSource,
    EnterpriseEntitlementPrincipalType,
)

from ..auth import User
from ..deps import AppStateDep
from ..entitlements import require_permission

router = APIRouter(prefix="/admin/enterprise-data", tags=["admin"])

_RequireEnterpriseData = Depends(require_permission("admin.enterprise_data"))


def _has_signing_secret(source: dict) -> bool:
    env_var = (source.get("connection_config") or {}).get("signing_secret_env_var")
    return bool(env_var and os.environ.get(env_var))


async def _rows_for_connector(state, source: dict, client_rows: list[dict[str, Any]], *, drain: bool) -> list[dict[str, Any]]:
    """`WEBHOOK` sources ignore whatever rows the admin's own request body
    carries -- their rows come from inbound pushes staged by
    `POST /webhooks/enterprise-data/{source_id}` -- while every other
    connector type uses the caller-supplied rows exactly as before
    (ignored by the pull connectors, meaningful only for `MANUAL_UPLOAD`)."""
    if source["connector_type"] != EnterpriseConnectorType.WEBHOOK.value:
        return client_rows
    if drain:
        return await state.repo.drain_enterprise_webhook_rows(source["id"])
    return await state.repo.list_staged_enterprise_webhook_rows(source["id"])


def _build_source_connector(source: dict, *, rows: list[dict[str, Any]]):
    return build_connector(
        connector_type=EnterpriseConnectorType(source["connector_type"]),
        source_id=source["id"],
        classification=EnterpriseDataClassification(source["classification"]),
        connection_config=source["connection_config"],
        rows=rows,
        has_signing_secret=_has_signing_secret(source),
    )


class SourceCreateRequest(BaseModel):
    organization_id: str
    workspace_id: str | None = None
    name: str
    connector_type: str
    classification: EnterpriseDataClassification
    description: str = ""
    connection_config: dict[str, Any] = {}


@router.get("/sources")
async def list_sources(
    state: AppStateDep,
    _admin: User = _RequireEnterpriseData,
    organization_id: str | None = None,
    workspace_id: str | None = None,
) -> list[dict]:
    return await state.repo.list_enterprise_data_sources(organization_id=organization_id, workspace_id=workspace_id)


@router.post("/sources", status_code=status.HTTP_201_CREATED)
async def create_source(body: SourceCreateRequest, state: AppStateDep, admin: User = _RequireEnterpriseData) -> dict:
    if await state.repo.get_organization(body.organization_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown organization_id")
    try:
        connector_type = EnterpriseConnectorType(body.connector_type)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown connector_type: {body.connector_type}")
    source = EnterpriseDataSource(
        organization_id=body.organization_id,
        workspace_id=body.workspace_id,
        name=body.name,
        connector_type=connector_type,
        classification=body.classification,
        description=body.description,
        connection_config=body.connection_config,
        created_by=admin.user_id,
    )
    await state.repo.save_enterprise_data_source(source)
    return await state.repo.get_enterprise_data_source(str(source.id))


@router.get("/sources/{source_id}")
async def get_source(source_id: str, state: AppStateDep, _admin: User = _RequireEnterpriseData) -> dict:
    source = await state.repo.get_enterprise_data_source(source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    return source


class SourceUpdateRequest(BaseModel):
    name: str | None = None
    status: str | None = None
    description: str | None = None
    connection_config: dict[str, Any] | None = None


@router.patch("/sources/{source_id}")
async def update_source(
    source_id: str, body: SourceUpdateRequest, state: AppStateDep, _admin: User = _RequireEnterpriseData
) -> dict:
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    updated = await state.repo.update_enterprise_data_source(source_id, **fields)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    return updated


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: str, state: AppStateDep, _admin: User = _RequireEnterpriseData) -> None:
    if not await state.repo.delete_enterprise_data_source(source_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")


class TestConnectionRequest(BaseModel):
    sample_rows: list[dict[str, Any]] = []


@router.post("/sources/{source_id}/test-connection")
async def test_connection(
    source_id: str, body: TestConnectionRequest, state: AppStateDep, _admin: User = _RequireEnterpriseData
) -> dict:
    source = await state.repo.get_enterprise_data_source(source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    rows = await _rows_for_connector(state, source, body.sample_rows, drain=False)
    connector = _build_source_connector(source, rows=rows)
    started = time.monotonic()
    health = await connector.test_connection()
    latency_ms = (time.monotonic() - started) * 1000
    return await state.repo.record_enterprise_data_event(
        source_id=source_id,
        event_type="test_connection",
        status="success" if health.status == "healthy" else "error",
        detail=health.detail,
        latency_ms=latency_ms,
    )


@router.get("/sources/{source_id}/events")
async def list_events(source_id: str, state: AppStateDep, _admin: User = _RequireEnterpriseData) -> list[dict]:
    if await state.repo.get_enterprise_data_source(source_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    return await state.repo.list_enterprise_data_events(source_id)


class DatasetCreateRequest(BaseModel):
    name: str
    domain: EnterpriseDataDomain
    classification: EnterpriseDataClassification
    sample_rows: list[dict[str, Any]] = []


@router.get("/sources/{source_id}/datasets")
async def list_datasets_for_source(source_id: str, state: AppStateDep, _admin: User = _RequireEnterpriseData) -> list[dict]:
    if await state.repo.get_enterprise_data_source(source_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    return await state.repo.list_enterprise_datasets(source_id=source_id)


@router.post("/sources/{source_id}/datasets", status_code=status.HTTP_201_CREATED)
async def create_dataset(
    source_id: str, body: DatasetCreateRequest, state: AppStateDep, _admin: User = _RequireEnterpriseData
) -> dict:
    source = await state.repo.get_enterprise_data_source(source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    rows = await _rows_for_connector(state, source, body.sample_rows, drain=False)
    connector = _build_source_connector(source, rows=rows)
    try:
        schema_fields = await connector.discover_schema()
    except NotImplementedError:
        # An unimplemented connector type (docs/alpha-intelligence.md section
        # 11.3) still lets an admin register the dataset -- just without a
        # discovered schema yet, rather than blocking dataset creation entirely.
        schema_fields = []
    dataset = EnterpriseDataset(
        source_id=source_id,
        organization_id=source["organization_id"],
        name=body.name,
        domain=body.domain,
        classification=body.classification,
        schema_summary={f.name: f.inferred_type for f in schema_fields},
    )
    await state.repo.save_enterprise_dataset(dataset)
    return await state.repo.get_enterprise_dataset(str(dataset.id))


@router.get("/datasets/{dataset_id}")
async def get_dataset(dataset_id: str, state: AppStateDep, _admin: User = _RequireEnterpriseData) -> dict:
    dataset = await state.repo.get_enterprise_dataset(dataset_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return dataset


class DatasetRowsRequest(BaseModel):
    rows: list[dict[str, Any]] = []


@router.post("/datasets/{dataset_id}/preview")
async def preview_dataset(
    dataset_id: str, body: DatasetRowsRequest, state: AppStateDep, _admin: User = _RequireEnterpriseData
) -> dict:
    dataset = await state.repo.get_enterprise_dataset(dataset_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    source = await state.repo.get_enterprise_data_source(dataset["source_id"])
    rows = await _rows_for_connector(state, source, body.rows, drain=False)
    connector = _build_source_connector(source, rows=rows)
    try:
        schema_fields = await connector.discover_schema()
        preview_rows = await connector.preview()
    except NotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {
        "schema": {f.name: f.inferred_type for f in schema_fields},
        "preview_rows": preview_rows,
    }


@router.post("/datasets/{dataset_id}/ingest")
async def ingest_dataset(
    dataset_id: str, body: DatasetRowsRequest, state: AppStateDep, _admin: User = _RequireEnterpriseData
) -> dict:
    dataset = await state.repo.get_enterprise_dataset(dataset_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    source = await state.repo.get_enterprise_data_source(dataset["source_id"])
    rows = await _rows_for_connector(state, source, body.rows, drain=True)
    connector = _build_source_connector(source, rows=rows)
    started = time.monotonic()
    try:
        result, accepted_rows = await connector.ingest()
    except NotImplementedError as exc:
        latency_ms = (time.monotonic() - started) * 1000
        await state.repo.record_enterprise_data_event(
            source_id=dataset["source_id"], event_type="ingest", status="error", detail=str(exc), latency_ms=latency_ms
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    latency_ms = (time.monotonic() - started) * 1000
    await state.repo.save_enterprise_records(dataset_id, accepted_rows)
    schema_fields = await connector.discover_schema()
    updated_dataset = await state.repo.update_enterprise_dataset_sync(
        dataset_id,
        schema_summary={f.name: f.inferred_type for f in schema_fields} or None,
        row_count=dataset["row_count"] + result.rows_ingested,
    )
    await state.repo.record_enterprise_data_event(
        source_id=dataset["source_id"],
        event_type="ingest",
        status="success" if not result.errors else "error",
        detail="; ".join(result.errors) or f"Ingested {result.rows_ingested} row(s)",
        rows_ingested=result.rows_ingested,
        rows_rejected=result.rows_rejected,
        latency_ms=latency_ms,
    )
    return {"dataset": updated_dataset, "rows_ingested": result.rows_ingested, "rows_rejected": result.rows_rejected, "errors": result.errors}


@router.get("/datasets/{dataset_id}/records")
async def list_records(
    dataset_id: str, state: AppStateDep, _admin: User = _RequireEnterpriseData, limit: int = 50
) -> list[dict]:
    if await state.repo.get_enterprise_dataset(dataset_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return await state.repo.list_enterprise_records(dataset_id, limit=limit)


class EntitlementCreateRequest(BaseModel):
    principal_type: EnterpriseEntitlementPrincipalType
    principal_id: str


@router.get("/datasets/{dataset_id}/entitlements")
async def list_entitlements(dataset_id: str, state: AppStateDep, _admin: User = _RequireEnterpriseData) -> list[dict]:
    if await state.repo.get_enterprise_dataset(dataset_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return await state.repo.list_enterprise_data_entitlements(dataset_id)


@router.post("/datasets/{dataset_id}/entitlements", status_code=status.HTTP_201_CREATED)
async def grant_entitlement(
    dataset_id: str, body: EntitlementCreateRequest, state: AppStateDep, admin: User = _RequireEnterpriseData
) -> list[dict]:
    if await state.repo.get_enterprise_dataset(dataset_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    entitlement = EnterpriseDataEntitlement(
        dataset_id=dataset_id,
        principal_type=body.principal_type,
        principal_id=body.principal_id,
        granted_by=admin.user_id,
    )
    await state.repo.save_enterprise_data_entitlement(entitlement)
    return await state.repo.list_enterprise_data_entitlements(dataset_id)


@router.delete("/datasets/{dataset_id}/entitlements/{entitlement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_entitlement(
    dataset_id: str, entitlement_id: str, state: AppStateDep, _admin: User = _RequireEnterpriseData
) -> None:
    if not await state.repo.delete_enterprise_data_entitlement(entitlement_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entitlement not found")
