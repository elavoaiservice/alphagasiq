"""`BaseEnterpriseDataConnector` and its six real implementations
(docs/alpha-intelligence.md section 11.3): `ManualUploadConnector`,
`WebhookConnector`, `RestApiConnector`, `DatabaseConnector`, `S3Connector`,
`SftpConnector`. Network/DB/SSH-touching connectors are exercised through
injected fakes (`http_client`/`client_factory`/`sftp_client_factory`) or, for
`DatabaseConnector`, a real ephemeral SQLite database via `aiosqlite` -- no
external credentials or real internet access required, matching every other
`Mock*Provider` in this codebase's "usable path with zero paid subscriptions"
discipline."""

from __future__ import annotations

import io
import json

import httpx
from botocore.exceptions import ClientError
from enterprise_data_service import build_connector
from enterprise_data_service.connector import (
    DatabaseConnector,
    ManualUploadConnector,
    RestApiConnector,
    S3Connector,
    SftpConnector,
    WebhookConnector,
)
from schemas import EnterpriseConnectorType, EnterpriseDataClassification

_CLASSIFICATION = EnterpriseDataClassification.CUSTOMER_CONFIDENTIAL


async def test_manual_upload_health_reports_staged_row_count():
    connector = build_connector(
        connector_type=EnterpriseConnectorType.MANUAL_UPLOAD, source_id="src-1", classification=_CLASSIFICATION, rows=[{"well_id": "W-1"}]
    )
    health = await connector.test_connection()
    assert health.status == "healthy"
    assert "1 row" in health.detail


async def test_manual_upload_health_degraded_when_no_rows_staged():
    connector = build_connector(connector_type=EnterpriseConnectorType.MANUAL_UPLOAD, source_id="src-1", classification=_CLASSIFICATION, rows=[])
    health = await connector.test_connection()
    assert health.status == "degraded"


async def test_manual_upload_discover_schema_infers_types():
    connector = build_connector(
        connector_type=EnterpriseConnectorType.MANUAL_UPLOAD,
        source_id="src-1",
        classification=_CLASSIFICATION,
        rows=[{"well_id": "W-1", "production_bbl": 120.5, "active": True, "date": "2026-01-01"}],
    )
    schema = await connector.discover_schema()
    by_name = {f.name: f.inferred_type for f in schema}
    assert by_name["well_id"] == "string"
    assert by_name["production_bbl"] == "number"
    assert by_name["active"] == "boolean"
    assert by_name["date"] == "datetime"


async def test_manual_upload_discover_schema_empty_when_no_rows():
    connector = build_connector(connector_type=EnterpriseConnectorType.MANUAL_UPLOAD, source_id="src-1", classification=_CLASSIFICATION, rows=[])
    assert await connector.discover_schema() == []


async def test_manual_upload_preview_respects_limit():
    rows = [{"i": i} for i in range(20)]
    connector = build_connector(connector_type=EnterpriseConnectorType.MANUAL_UPLOAD, source_id="src-1", classification=_CLASSIFICATION, rows=rows)
    preview = await connector.preview(limit=5)
    assert len(preview) == 5


async def test_manual_upload_ingest_rejects_non_dict_and_empty_rows():
    connector = build_connector(
        connector_type=EnterpriseConnectorType.MANUAL_UPLOAD, source_id="src-1", classification=_CLASSIFICATION, rows=[{"a": 1}, {}, "not-a-dict"]
    )
    result, accepted = await connector.ingest()
    assert result.rows_ingested == 1
    assert result.rows_rejected == 2
    assert accepted == [{"a": 1}]
    assert result.errors


async def test_manual_upload_ingest_all_valid_has_no_errors():
    connector = build_connector(
        connector_type=EnterpriseConnectorType.MANUAL_UPLOAD, source_id="src-1", classification=_CLASSIFICATION, rows=[{"a": 1}, {"a": 2}]
    )
    result, accepted = await connector.ingest()
    assert result.rows_ingested == 2
    assert result.rows_rejected == 0
    assert result.errors == []
    assert len(accepted) == 2


def test_build_connector_falls_back_to_manual_upload_and_webhook_directly():
    assert isinstance(
        build_connector(connector_type=EnterpriseConnectorType.MANUAL_UPLOAD, source_id="s", classification=_CLASSIFICATION), ManualUploadConnector
    )
    assert isinstance(
        build_connector(connector_type=EnterpriseConnectorType.WEBHOOK, source_id="s", classification=_CLASSIFICATION), WebhookConnector
    )


# -- WebhookConnector --------------------------------------------------------


async def test_webhook_not_configured_without_signing_secret():
    connector = WebhookConnector(source_id="s1", classification=_CLASSIFICATION, rows=[{"a": 1}], has_signing_secret=False)
    health = await connector.test_connection()
    assert health.status == "not_configured"


async def test_webhook_degraded_when_secret_configured_but_no_rows_yet():
    connector = WebhookConnector(source_id="s1", classification=_CLASSIFICATION, rows=[], has_signing_secret=True)
    health = await connector.test_connection()
    assert health.status == "degraded"


async def test_webhook_healthy_with_secret_and_staged_rows():
    connector = WebhookConnector(source_id="s1", classification=_CLASSIFICATION, rows=[{"a": 1}], has_signing_secret=True)
    health = await connector.test_connection()
    assert health.status == "healthy"
    result, accepted = await connector.ingest()
    assert result.rows_ingested == 1
    assert accepted == [{"a": 1}]


# -- RestApiConnector ---------------------------------------------------------


async def test_rest_api_not_configured_without_url():
    connector = RestApiConnector(source_id="s1", classification=_CLASSIFICATION, connection_config={})
    health = await connector.test_connection()
    assert health.status == "not_configured"


async def test_rest_api_healthy_and_preview_fetches_real_rows_over_mock_transport():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=[{"a": 1}, {"a": 2}]))
    connector = RestApiConnector(
        source_id="s1",
        classification=_CLASSIFICATION,
        connection_config={"url": "https://example.test/data"},
        http_client=httpx.AsyncClient(transport=transport),
    )
    health = await connector.test_connection()
    assert health.status == "healthy"

    rows = await connector.preview()
    assert rows == [{"a": 1}, {"a": 2}]

    result, accepted = await connector.ingest()
    assert result.rows_ingested == 2
    assert accepted == [{"a": 1}, {"a": 2}]


async def test_rest_api_extracts_rows_under_wrapper_key():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": [{"a": 1}]}))
    connector = RestApiConnector(
        source_id="s1", classification=_CLASSIFICATION, connection_config={"url": "https://example.test"}, http_client=httpx.AsyncClient(transport=transport)
    )
    schema = await connector.discover_schema()
    assert [f.name for f in schema] == ["a"]


async def test_rest_api_records_path_walks_nested_wrapper():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"envelope": {"rows": [{"b": 2}]}}))
    connector = RestApiConnector(
        source_id="s1",
        classification=_CLASSIFICATION,
        connection_config={"url": "https://example.test", "records_path": "envelope.rows"},
        http_client=httpx.AsyncClient(transport=transport),
    )
    rows = await connector.preview()
    assert rows == [{"b": 2}]


async def test_rest_api_injects_auth_header_from_env_var(monkeypatch):
    monkeypatch.setenv("MY_API_TOKEN", "secret-123")
    captured: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    connector = RestApiConnector(
        source_id="s1",
        classification=_CLASSIFICATION,
        connection_config={"url": "https://example.test", "auth_header_env_var": "MY_API_TOKEN"},
        http_client=httpx.AsyncClient(transport=transport),
    )
    await connector.preview()
    assert captured["auth"] == "secret-123"


async def test_rest_api_degraded_on_http_error_status():
    transport = httpx.MockTransport(lambda request: httpx.Response(500, json={"error": "boom"}))
    connector = RestApiConnector(
        source_id="s1", classification=_CLASSIFICATION, connection_config={"url": "https://example.test"}, http_client=httpx.AsyncClient(transport=transport)
    )
    health = await connector.test_connection()
    assert health.status == "degraded"


async def test_rest_api_unavailable_on_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    connector = RestApiConnector(
        source_id="s1",
        classification=_CLASSIFICATION,
        connection_config={"url": "https://example.test"},
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    health = await connector.test_connection()
    assert health.status == "unavailable"


# -- DatabaseConnector ---------------------------------------------------------


async def test_database_not_configured_without_env_var():
    connector = DatabaseConnector(source_id="s1", classification=_CLASSIFICATION, connection_config={"query": "SELECT 1"})
    health = await connector.test_connection()
    assert health.status == "not_configured"


async def test_database_rejects_non_select_query(monkeypatch):
    monkeypatch.setenv("TEST_ENTERPRISE_DB_URL", "sqlite+aiosqlite:///:memory:")
    connector = DatabaseConnector(
        source_id="s1", classification=_CLASSIFICATION, connection_config={"connection_string_env_var": "TEST_ENTERPRISE_DB_URL", "query": "DELETE FROM foo"}
    )
    health = await connector.test_connection()
    assert health.status == "not_configured"
    assert "read-only" in health.detail


async def test_database_connects_to_a_real_sqlite_db_and_fetches_rows(monkeypatch):
    monkeypatch.setenv("TEST_ENTERPRISE_DB_URL", "sqlite+aiosqlite:///:memory:")
    connector = DatabaseConnector(
        source_id="s1",
        classification=_CLASSIFICATION,
        connection_config={"connection_string_env_var": "TEST_ENTERPRISE_DB_URL", "query": "SELECT 1 AS one, 'x' AS label"},
    )
    health = await connector.test_connection()
    assert health.status == "healthy"

    rows = await connector.preview()
    assert rows == [{"one": 1, "label": "x"}]

    result, accepted = await connector.ingest()
    assert result.rows_ingested == 1
    assert accepted == [{"one": 1, "label": "x"}]


async def test_database_unavailable_on_invalid_connection_url(monkeypatch):
    monkeypatch.setenv("TEST_ENTERPRISE_DB_BAD_URL", "not-a-valid-sqlalchemy-url")
    connector = DatabaseConnector(
        source_id="s1", classification=_CLASSIFICATION, connection_config={"connection_string_env_var": "TEST_ENTERPRISE_DB_BAD_URL", "query": "SELECT 1"}
    )
    health = await connector.test_connection()
    assert health.status == "unavailable"


# -- S3Connector ----------------------------------------------------------------


class _FakeS3Client:
    def __init__(self, objects: dict[str, bytes]):
        self._objects = objects

    def list_objects_v2(self, *, Bucket, Prefix="", MaxKeys=50):
        keys = sorted(k for k in self._objects if k.startswith(Prefix))
        return {"Contents": [{"Key": k} for k in keys[:MaxKeys]]}

    def get_object(self, *, Bucket, Key):
        return {"Body": io.BytesIO(self._objects[Key])}


async def test_s3_not_configured_without_bucket():
    connector = S3Connector(source_id="s1", classification=_CLASSIFICATION, connection_config={})
    health = await connector.test_connection()
    assert health.status == "not_configured"


async def test_s3_lists_and_fetches_json_object_via_injected_client():
    fake_client = _FakeS3Client({"data/rows.json": json.dumps([{"a": 1}, {"a": 2}]).encode()})
    connector = S3Connector(
        source_id="s1",
        classification=_CLASSIFICATION,
        connection_config={"bucket": "my-bucket", "prefix": "data/"},
        client_factory=lambda: fake_client,
    )
    health = await connector.test_connection()
    assert health.status == "healthy"

    rows = await connector.preview()
    assert rows == [{"a": 1}, {"a": 2}]

    result, accepted = await connector.ingest()
    assert result.rows_ingested == 2


async def test_s3_parses_csv_object():
    fake_client = _FakeS3Client({"data/rows.csv": b"a,b\n1,x\n2,y\n"})
    connector = S3Connector(
        source_id="s1", classification=_CLASSIFICATION, connection_config={"bucket": "my-bucket", "prefix": "data/"}, client_factory=lambda: fake_client
    )
    rows = await connector.preview()
    assert rows == [{"a": "1", "b": "x"}, {"a": "2", "b": "y"}]


async def test_s3_unavailable_when_client_raises_client_error():
    class _FailingClient:
        def list_objects_v2(self, **kwargs):
            raise ClientError({"Error": {"Code": "403", "Message": "Forbidden"}}, "ListObjectsV2")

    connector = S3Connector(source_id="s1", classification=_CLASSIFICATION, connection_config={"bucket": "b"}, client_factory=lambda: _FailingClient())
    health = await connector.test_connection()
    assert health.status == "unavailable"


# -- SftpConnector ----------------------------------------------------------------


class _FakeSftpSession:
    def __init__(self, content: bytes):
        self._content = content
        self.closed = False

    def stat(self, path):
        return object()

    def open(self, path, mode="r"):
        return io.BytesIO(self._content)

    def close(self):
        self.closed = True


async def test_sftp_not_configured_without_host():
    connector = SftpConnector(source_id="s1", classification=_CLASSIFICATION, connection_config={})
    health = await connector.test_connection()
    assert health.status == "not_configured"


async def test_sftp_fetches_rows_via_injected_session_and_closes_it():
    session = _FakeSftpSession(json.dumps([{"well": "A"}]).encode())
    connector = SftpConnector(
        source_id="s1",
        classification=_CLASSIFICATION,
        connection_config={"host": "sftp.example.test", "username": "u", "remote_path": "/data/rows.json"},
        sftp_client_factory=lambda: session,
    )
    health = await connector.test_connection()
    assert health.status == "healthy"
    assert session.closed

    session.closed = False
    rows = await connector.preview()
    assert rows == [{"well": "A"}]
    assert session.closed


async def test_sftp_unavailable_when_session_raises():
    class _FailingSession:
        def stat(self, path):
            raise OSError("no route to host")

        def close(self):
            pass

    connector = SftpConnector(
        source_id="s1",
        classification=_CLASSIFICATION,
        connection_config={"host": "h", "username": "u", "remote_path": "/x"},
        sftp_client_factory=lambda: _FailingSession(),
    )
    health = await connector.test_connection()
    assert health.status == "unavailable"
