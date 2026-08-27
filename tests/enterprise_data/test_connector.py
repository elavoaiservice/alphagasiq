"""`BaseEnterpriseDataConnector`/`ManualUploadConnector`/`NotImplementedConnector`
(docs/alpha-intelligence.md section 11.3, Milestone 8)."""

from __future__ import annotations

import pytest
from enterprise_data_service import build_connector
from schemas import EnterpriseConnectorType, EnterpriseDataClassification


async def test_manual_upload_health_reports_staged_row_count():
    connector = build_connector(
        connector_type=EnterpriseConnectorType.MANUAL_UPLOAD,
        source_id="src-1",
        classification=EnterpriseDataClassification.CUSTOMER_CONFIDENTIAL,
        rows=[{"well_id": "W-1"}],
    )
    health = await connector.test_connection()
    assert health.status == "healthy"
    assert "1 row" in health.detail


async def test_manual_upload_health_degraded_when_no_rows_staged():
    connector = build_connector(
        connector_type=EnterpriseConnectorType.MANUAL_UPLOAD,
        source_id="src-1",
        classification=EnterpriseDataClassification.CUSTOMER_CONFIDENTIAL,
        rows=[],
    )
    health = await connector.test_connection()
    assert health.status == "degraded"


async def test_manual_upload_discover_schema_infers_types():
    connector = build_connector(
        connector_type=EnterpriseConnectorType.MANUAL_UPLOAD,
        source_id="src-1",
        classification=EnterpriseDataClassification.CUSTOMER_CONFIDENTIAL,
        rows=[{"well_id": "W-1", "production_bbl": 120.5, "active": True, "date": "2026-01-01"}],
    )
    schema = await connector.discover_schema()
    by_name = {f.name: f.inferred_type for f in schema}
    assert by_name["well_id"] == "string"
    assert by_name["production_bbl"] == "number"
    assert by_name["active"] == "boolean"
    assert by_name["date"] == "datetime"


async def test_manual_upload_discover_schema_empty_when_no_rows():
    connector = build_connector(
        connector_type=EnterpriseConnectorType.MANUAL_UPLOAD,
        source_id="src-1",
        classification=EnterpriseDataClassification.CUSTOMER_CONFIDENTIAL,
        rows=[],
    )
    assert await connector.discover_schema() == []


async def test_manual_upload_preview_respects_limit():
    rows = [{"i": i} for i in range(20)]
    connector = build_connector(
        connector_type=EnterpriseConnectorType.MANUAL_UPLOAD,
        source_id="src-1",
        classification=EnterpriseDataClassification.CUSTOMER_CONFIDENTIAL,
        rows=rows,
    )
    preview = await connector.preview(limit=5)
    assert len(preview) == 5


async def test_manual_upload_ingest_rejects_non_dict_and_empty_rows():
    connector = build_connector(
        connector_type=EnterpriseConnectorType.MANUAL_UPLOAD,
        source_id="src-1",
        classification=EnterpriseDataClassification.CUSTOMER_CONFIDENTIAL,
        rows=[{"a": 1}, {}, "not-a-dict"],
    )
    result, accepted = await connector.ingest()
    assert result.rows_ingested == 1
    assert result.rows_rejected == 2
    assert accepted == [{"a": 1}]
    assert result.errors


async def test_manual_upload_ingest_all_valid_has_no_errors():
    connector = build_connector(
        connector_type=EnterpriseConnectorType.MANUAL_UPLOAD,
        source_id="src-1",
        classification=EnterpriseDataClassification.CUSTOMER_CONFIDENTIAL,
        rows=[{"a": 1}, {"a": 2}],
    )
    result, accepted = await connector.ingest()
    assert result.rows_ingested == 2
    assert result.rows_rejected == 0
    assert result.errors == []
    assert len(accepted) == 2


@pytest.mark.parametrize(
    "connector_type",
    [
        EnterpriseConnectorType.REST_API,
        EnterpriseConnectorType.SFTP,
        EnterpriseConnectorType.DATABASE,
        EnterpriseConnectorType.S3,
        EnterpriseConnectorType.WEBHOOK,
    ],
)
async def test_unimplemented_connector_types_report_not_configured_honestly(connector_type):
    connector = build_connector(
        connector_type=connector_type, source_id="src-1", classification=EnterpriseDataClassification.PUBLIC
    )
    health = await connector.test_connection()
    assert health.status == "not_configured"
    assert connector_type.value in health.detail

    with pytest.raises(NotImplementedError):
        await connector.discover_schema()
    with pytest.raises(NotImplementedError):
        await connector.preview()
    with pytest.raises(NotImplementedError):
        await connector.ingest()
