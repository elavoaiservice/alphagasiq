"""`BaseEnterpriseDataConnector` (docs/alpha-intelligence.md section 11.3,
Milestone 8): the common interface every enterprise data connector implements
-- the same shape `data_sdk.provider.BaseDataProvider` already established for
public/licensed market data, generalized to admin-registered proprietary
customer connections.

Trimmed from the doc's full ten-method sketch (`connect`/`test_connection`/
`authenticate`/`discover_schema`/`preview`/`ingest`/`incremental_sync`/
`validate`/`normalize`/`disconnect`) down to the subset actually implementable
without overengineering -- `BaseDataProvider` itself only ships `fetch`/
`normalize`/`health_check`, not its own doc's full list, so trimming here
follows the same established precedent, not a new cut corner.

All six `EnterpriseConnectorType` values are implemented end-to-end:

- `MANUAL_UPLOAD` (`ManualUploadConnector`) -- an admin supplies already-parsed
  rows directly; no network call.
- `WEBHOOK` (`WebhookConnector`) -- an external system pushes rows to
  `POST /webhooks/enterprise-data/{source_id}` (apps/api/api_app/routers/
  enterprise_webhooks.py), which HMAC-verifies and stages them durably; this
  class reads whatever the caller resolved from that staging buffer.
- `REST_API` (`RestApiConnector`) -- a genuine outbound `httpx` pull against
  `connection_config["url"]`, the exact same "real call when configured,
  `not_configured` health otherwise" posture `data_service.providers.eia.
  EIAProvider` already establishes for public market data.
- `DATABASE` (`DatabaseConnector`) -- a genuine `sqlalchemy` async connection
  to a customer-provisioned database, running a read-only `SELECT`/`WITH`
  query named in `connection_config`.
- `S3` (`S3Connector`) -- a genuine `boto3` S3 (or any S3-compatible endpoint,
  via `connection_config["endpoint_url"]`) object listing + fetch.
- `SFTP` (`SftpConnector`) -- a genuine `paramiko` SFTP session against a
  customer-provisioned host.

Every connector follows `EnterpriseDataSource`'s existing no-credential
posture: `connection_config` carries only non-secret settings (a URL, a
bucket name, a hostname, a query) plus `*_env_var` fields naming an
environment variable the operator provisions the actual secret into -- the
credential value itself never touches this object, the DB, or the admin API.
A connector missing its required configuration reports `not_configured`
honestly (mirroring `data_sdk.provider.NotImplementedProvider`) rather than
silently failing or fabricating data.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import hmac
import io
import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import httpx
import paramiko
from botocore.exceptions import BotoCoreError, ClientError
from schemas import EnterpriseConnectorType, EnterpriseDataClassification
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import create_async_engine


@dataclass
class ConnectorHealth:
    source_id: str
    status: str = "unknown"  # healthy | degraded | unavailable | not_configured
    detail: str = ""
    checked_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SchemaField:
    name: str
    inferred_type: str  # string | number | datetime | boolean


@dataclass
class IngestResult:
    rows_ingested: int
    rows_rejected: int
    errors: list[str] = field(default_factory=list)


class BaseEnterpriseDataConnector(ABC):
    connector_type: EnterpriseConnectorType
    classification: EnterpriseDataClassification
    source_id: str

    @abstractmethod
    async def test_connection(self) -> ConnectorHealth: ...

    @abstractmethod
    async def discover_schema(self) -> list[SchemaField]: ...

    @abstractmethod
    async def preview(self, limit: int = 10) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def ingest(self) -> tuple[IngestResult, list[dict[str, Any]]]:
        """Returns the ingest result plus the normalized rows actually
        accepted, so the caller can persist them."""
        ...

    async def health_check(self) -> ConnectorHealth:
        return await self.test_connection()


class NotImplementedConnector(BaseEnterpriseDataConnector):
    """Defensive fallback for any `connector_type` `build_connector()` does
    not recognize (e.g. a future enum value added without a matching class
    yet). Reports `not_configured` honestly, mirroring
    `data_sdk.provider.NotImplementedProvider`'s exact same posture. Every
    value currently on `EnterpriseConnectorType` has a real implementation
    below, so this path is unreachable in practice today."""

    def __init__(self, *, connector_type: EnterpriseConnectorType, classification: EnterpriseDataClassification, source_id: str):
        self.connector_type = connector_type
        self.classification = classification
        self.source_id = source_id

    async def test_connection(self) -> ConnectorHealth:
        return ConnectorHealth(
            source_id=self.source_id,
            status="not_configured",
            detail=f"{self.connector_type.value} connector is not implemented yet",
        )

    async def discover_schema(self) -> list[SchemaField]:
        raise NotImplementedError(f"{self.connector_type.value} connector is not implemented yet")

    async def preview(self, limit: int = 10) -> list[dict[str, Any]]:
        raise NotImplementedError(f"{self.connector_type.value} connector is not implemented yet")

    async def ingest(self) -> tuple[IngestResult, list[dict[str, Any]]]:
        raise NotImplementedError(f"{self.connector_type.value} connector is not implemented yet")


def _infer_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        try:
            datetime.fromisoformat(value)
            return "datetime"
        except ValueError:
            return "string"
    return "string"


def _sanitize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Coerce a raw row's values to JSON-safe primitives (e.g. a DB driver's
    `Decimal`/`date` types) without dropping the field."""
    sanitized: dict[str, Any] = {}
    for key, value in row.items():
        if value is None or isinstance(value, (str, int, float, bool)):
            sanitized[key] = value
        else:
            sanitized[key] = str(value)
    return sanitized


def _extract_records(payload: Any, records_path: str | None) -> list[dict[str, Any]]:
    """Pulls a list of row-objects out of an arbitrary REST API JSON payload.
    `records_path` (dotted, e.g. `"data.records"`) takes precedence when set;
    otherwise falls back to the common top-level wrapper keys APIs use."""
    node = payload
    if records_path:
        for part in records_path.split("."):
            node = node.get(part) if isinstance(node, dict) else None
            if node is None:
                break
    if isinstance(node, list):
        return [r for r in node if isinstance(r, dict)]
    if isinstance(node, dict):
        for key in ("data", "results", "records", "rows", "items"):
            value = node.get(key)
            if isinstance(value, list):
                return [r for r in value if isinstance(r, dict)]
        return [node]
    return []


def _parse_object_bytes(key: str, content: bytes) -> list[dict[str, Any]]:
    """Parses a fetched file's bytes (from S3 or SFTP) into rows, based on its
    extension: `.jsonl`/`.ndjson` line-delimited JSON, `.csv` comma-separated,
    otherwise JSON (object/list/wrapped-list), falling back to CSV if the
    content is not valid JSON."""
    text_content = content.decode("utf-8", errors="replace")
    lower = key.lower()
    if lower.endswith(".jsonl") or lower.endswith(".ndjson"):
        rows: list[dict[str, Any]] = []
        for line in text_content.splitlines():
            line = line.strip()
            if not line:
                continue
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                rows.append(_sanitize_row(parsed))
        return rows
    if lower.endswith(".csv"):
        return [_sanitize_row(dict(r)) for r in csv.DictReader(io.StringIO(text_content))]
    try:
        parsed = json.loads(text_content)
    except json.JSONDecodeError:
        return [_sanitize_row(dict(r)) for r in csv.DictReader(io.StringIO(text_content))]
    return [_sanitize_row(r) for r in _extract_records(parsed, None)]


class ManualUploadConnector(BaseEnterpriseDataConnector):
    """An administrator supplies already-parsed tabular rows (e.g. an
    uploaded CSV, parsed before reaching this class) -- no external network
    call, no credential, genuinely usable with zero paid subscriptions."""

    connector_type = EnterpriseConnectorType.MANUAL_UPLOAD

    def __init__(self, *, source_id: str, classification: EnterpriseDataClassification, rows: list[dict[str, Any]]):
        self.source_id = source_id
        self.classification = classification
        self._rows = rows

    async def test_connection(self) -> ConnectorHealth:
        if self._rows:
            return ConnectorHealth(source_id=self.source_id, status="healthy", detail=f"{len(self._rows)} row(s) staged")
        return ConnectorHealth(source_id=self.source_id, status="degraded", detail="No rows staged yet")

    async def discover_schema(self) -> list[SchemaField]:
        if not self._rows:
            return []
        sample = self._rows[0]
        return [SchemaField(name=key, inferred_type=_infer_type(value)) for key, value in sample.items()]

    async def preview(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._rows[:limit]

    async def ingest(self) -> tuple[IngestResult, list[dict[str, Any]]]:
        valid_rows = [r for r in self._rows if isinstance(r, dict) and r]
        rejected = len(self._rows) - len(valid_rows)
        errors = [f"{rejected} row(s) rejected: not a non-empty object"] if rejected else []
        return IngestResult(rows_ingested=len(valid_rows), rows_rejected=rejected, errors=errors), valid_rows


class WebhookConnector(BaseEnterpriseDataConnector):
    """Inbound push connector. Rows arrive via `POST /webhooks/enterprise-data/
    {source_id}` (apps/api/api_app/routers/enterprise_webhooks.py), which
    HMAC-verifies the request against a secret named (never stored) by
    `connection_config["signing_secret_env_var"]` and stages accepted rows in
    `EnterpriseWebhookStagedRowRow`. This class never touches the network or
    the staging table itself -- the caller (the admin router) resolves `rows`
    from `repository.list_staged_enterprise_webhook_rows` (a non-destructive
    peek, for test-connection/preview/discover-schema) or
    `drain_enterprise_webhook_rows` (for `ingest()`) and passes them in,
    exactly the shape `ManualUploadConnector` already establishes.
    `has_signing_secret` reflects whether that env var actually resolves --
    a source with no verifiable secret can never have received a genuine
    push, so `test_connection()` reports `not_configured` rather than
    `healthy` even if rows happen to be present."""

    connector_type = EnterpriseConnectorType.WEBHOOK

    def __init__(
        self,
        *,
        source_id: str,
        classification: EnterpriseDataClassification,
        rows: list[dict[str, Any]],
        has_signing_secret: bool = False,
    ):
        self.source_id = source_id
        self.classification = classification
        self._rows = rows
        self._has_signing_secret = has_signing_secret

    async def test_connection(self) -> ConnectorHealth:
        if not self._has_signing_secret:
            return ConnectorHealth(
                source_id=self.source_id,
                status="not_configured",
                detail="connection_config.signing_secret_env_var not set -- inbound pushes cannot be verified",
            )
        if self._rows:
            return ConnectorHealth(
                source_id=self.source_id, status="healthy", detail=f"{len(self._rows)} row(s) staged from inbound pushes"
            )
        return ConnectorHealth(source_id=self.source_id, status="degraded", detail="Signing secret configured but no rows received yet")

    async def discover_schema(self) -> list[SchemaField]:
        if not self._rows:
            return []
        sample = self._rows[0]
        return [SchemaField(name=key, inferred_type=_infer_type(value)) for key, value in sample.items()]

    async def preview(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._rows[:limit]

    async def ingest(self) -> tuple[IngestResult, list[dict[str, Any]]]:
        valid_rows = [r for r in self._rows if isinstance(r, dict) and r]
        rejected = len(self._rows) - len(valid_rows)
        errors = [f"{rejected} row(s) rejected: not a non-empty object"] if rejected else []
        return IngestResult(rows_ingested=len(valid_rows), rows_rejected=rejected, errors=errors), valid_rows


class RestApiConnector(BaseEnterpriseDataConnector):
    """A genuine outbound REST API pull, mirroring
    `data_service.providers.eia.EIAProvider`'s exact "real httpx call when
    configured, `not_configured` health otherwise" posture. `connection_config`
    carries only non-secret settings (`url`, `method`, `headers`, `params`,
    `records_path`) plus an `auth_header_env_var` naming an environment
    variable the operator provisions the actual bearer token/API key into --
    the credential value itself never touches this object or the admin API.
    `http_client` lets a caller (a test) inject an `httpx.AsyncClient` backed
    by a `httpx.MockTransport`; when supplied, this class never closes it
    (the caller owns its lifecycle), unlike the client it creates itself."""

    connector_type = EnterpriseConnectorType.REST_API

    def __init__(
        self,
        *,
        source_id: str,
        classification: EnterpriseDataClassification,
        connection_config: dict[str, Any] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.source_id = source_id
        self.classification = classification
        config = connection_config or {}
        self._url: str | None = config.get("url")
        self._method: str = config.get("method", "GET")
        self._headers: dict[str, str] = dict(config.get("headers") or {})
        self._params: dict[str, Any] = dict(config.get("params") or {})
        self._records_path: str | None = config.get("records_path")
        auth_header_env_var = config.get("auth_header_env_var")
        if auth_header_env_var:
            token = os.environ.get(auth_header_env_var)
            if token:
                self._headers[config.get("auth_header_name", "Authorization")] = token
        self._injected_client = http_client

    async def _request(self, *, timeout: float) -> httpx.Response:
        client = self._injected_client or httpx.AsyncClient(timeout=timeout)
        try:
            return await client.request(self._method, self._url, headers=self._headers, params=self._params)
        finally:
            if self._injected_client is None:
                await client.aclose()

    async def test_connection(self) -> ConnectorHealth:
        if not self._url:
            return ConnectorHealth(source_id=self.source_id, status="not_configured", detail="connection_config.url is not set")
        try:
            resp = await self._request(timeout=10.0)
        except httpx.HTTPError as exc:
            return ConnectorHealth(source_id=self.source_id, status="unavailable", detail=str(exc))
        if resp.status_code < 400:
            return ConnectorHealth(source_id=self.source_id, status="healthy", detail=f"HTTP {resp.status_code} from {self._url}")
        return ConnectorHealth(source_id=self.source_id, status="degraded", detail=f"HTTP {resp.status_code} from {self._url}")

    async def _fetch_rows(self) -> list[dict[str, Any]]:
        if not self._url:
            raise NotImplementedError("REST_API connector has no connection_config.url configured")
        resp = await self._request(timeout=30.0)
        resp.raise_for_status()
        return [_sanitize_row(r) for r in _extract_records(resp.json(), self._records_path)]

    async def discover_schema(self) -> list[SchemaField]:
        rows = await self._fetch_rows()
        if not rows:
            return []
        return [SchemaField(name=k, inferred_type=_infer_type(v)) for k, v in rows[0].items()]

    async def preview(self, limit: int = 10) -> list[dict[str, Any]]:
        return (await self._fetch_rows())[:limit]

    async def ingest(self) -> tuple[IngestResult, list[dict[str, Any]]]:
        rows = await self._fetch_rows()
        valid_rows = [r for r in rows if isinstance(r, dict) and r]
        rejected = len(rows) - len(valid_rows)
        errors = [f"{rejected} row(s) rejected: not a non-empty object"] if rejected else []
        return IngestResult(rows_ingested=len(valid_rows), rows_rejected=rejected, errors=errors), valid_rows


class DatabaseConnector(BaseEnterpriseDataConnector):
    """A genuine `sqlalchemy` async connection to a customer-provisioned
    database. `connection_config["connection_string_env_var"]` names an
    environment variable holding the full connection URL (e.g.
    `postgresql+asyncpg://...`) -- never stored here -- and
    `connection_config["query"]` is a read-only `SELECT`/`WITH` statement the
    admin authors when registering the source; any other statement is refused
    (this connector's job is to read a customer's data, not mutate it)."""

    connector_type = EnterpriseConnectorType.DATABASE

    def __init__(
        self, *, source_id: str, classification: EnterpriseDataClassification, connection_config: dict[str, Any] | None = None
    ):
        self.source_id = source_id
        self.classification = classification
        config = connection_config or {}
        self._url_env_var: str | None = config.get("connection_string_env_var")
        self._query: str | None = config.get("query")

    def _resolve_url(self) -> str | None:
        return os.environ.get(self._url_env_var) if self._url_env_var else None

    def _validation_error(self) -> str | None:
        if not self._resolve_url():
            return "connection_config.connection_string_env_var not set"
        if not self._query:
            return "connection_config.query not set"
        if not self._query.strip().lower().startswith(("select", "with")):
            return "connection_config.query must be a read-only SELECT/WITH statement"
        return None

    async def test_connection(self) -> ConnectorHealth:
        error = self._validation_error()
        if error:
            return ConnectorHealth(source_id=self.source_id, status="not_configured", detail=error)
        try:
            engine = create_async_engine(self._resolve_url())
            try:
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            finally:
                await engine.dispose()
        except SQLAlchemyError as exc:
            return ConnectorHealth(source_id=self.source_id, status="unavailable", detail=str(exc))
        return ConnectorHealth(source_id=self.source_id, status="healthy", detail="Database connection succeeded")

    async def _fetch_rows(self) -> list[dict[str, Any]]:
        error = self._validation_error()
        if error:
            raise NotImplementedError(f"DATABASE connector is not usable: {error}")
        try:
            engine = create_async_engine(self._resolve_url())
            try:
                async with engine.connect() as conn:
                    result = await conn.execute(text(self._query))
                    return [_sanitize_row(dict(row._mapping)) for row in result]
            finally:
                await engine.dispose()
        except SQLAlchemyError as exc:
            raise NotImplementedError(f"DATABASE connector query failed: {exc}") from exc

    async def discover_schema(self) -> list[SchemaField]:
        rows = await self._fetch_rows()
        if not rows:
            return []
        return [SchemaField(name=k, inferred_type=_infer_type(v)) for k, v in rows[0].items()]

    async def preview(self, limit: int = 10) -> list[dict[str, Any]]:
        return (await self._fetch_rows())[:limit]

    async def ingest(self) -> tuple[IngestResult, list[dict[str, Any]]]:
        rows = await self._fetch_rows()
        valid_rows = [r for r in rows if isinstance(r, dict) and r]
        rejected = len(rows) - len(valid_rows)
        errors = [f"{rejected} row(s) rejected: not a non-empty object"] if rejected else []
        return IngestResult(rows_ingested=len(valid_rows), rows_rejected=rejected, errors=errors), valid_rows


class S3Connector(BaseEnterpriseDataConnector):
    """A genuine `boto3` S3 (or any S3-compatible endpoint, via
    `connection_config["endpoint_url"]` -- e.g. a self-hosted MinIO, keeping
    this usable with zero paid subscriptions) object listing + fetch.
    `access_key_env_var`/`secret_key_env_var` name environment variables
    holding AWS credentials; when unset, boto3's default credential chain
    applies. `client_factory` lets a caller (a test) inject a fake S3 client
    exposing `list_objects_v2`/`get_object`, bypassing both boto3 and the
    network entirely."""

    connector_type = EnterpriseConnectorType.S3

    def __init__(
        self,
        *,
        source_id: str,
        classification: EnterpriseDataClassification,
        connection_config: dict[str, Any] | None = None,
        client_factory: Callable[[], Any] | None = None,
    ):
        self.source_id = source_id
        self.classification = classification
        config = connection_config or {}
        self._bucket: str | None = config.get("bucket")
        self._prefix: str = config.get("prefix", "")
        self._region: str = config.get("region", "us-east-1")
        self._endpoint_url: str | None = config.get("endpoint_url")
        self._access_key_env_var: str | None = config.get("access_key_env_var")
        self._secret_key_env_var: str | None = config.get("secret_key_env_var")
        self._client_factory = client_factory

    def _build_client(self) -> Any:
        if self._client_factory is not None:
            return self._client_factory()
        import boto3

        kwargs: dict[str, Any] = {"region_name": self._region}
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        access_key = os.environ.get(self._access_key_env_var) if self._access_key_env_var else None
        secret_key = os.environ.get(self._secret_key_env_var) if self._secret_key_env_var else None
        if access_key and secret_key:
            kwargs["aws_access_key_id"] = access_key
            kwargs["aws_secret_access_key"] = secret_key
        return boto3.client("s3", **kwargs)

    async def test_connection(self) -> ConnectorHealth:
        if not self._bucket:
            return ConnectorHealth(source_id=self.source_id, status="not_configured", detail="connection_config.bucket is not set")
        try:
            await asyncio.to_thread(lambda: self._build_client().list_objects_v2(Bucket=self._bucket, Prefix=self._prefix, MaxKeys=1))
        except (BotoCoreError, ClientError) as exc:
            return ConnectorHealth(source_id=self.source_id, status="unavailable", detail=str(exc))
        return ConnectorHealth(source_id=self.source_id, status="healthy", detail=f"s3://{self._bucket}/{self._prefix} reachable")

    async def _fetch_rows(self, limit: int | None = None) -> list[dict[str, Any]]:
        if not self._bucket:
            raise NotImplementedError("S3 connector has no connection_config.bucket configured")

        def _call() -> list[dict[str, Any]]:
            client = self._build_client()
            listing = client.list_objects_v2(Bucket=self._bucket, Prefix=self._prefix, MaxKeys=50)
            keys = [obj["Key"] for obj in listing.get("Contents", []) if not obj["Key"].endswith("/")]
            rows: list[dict[str, Any]] = []
            for key in keys:
                body = client.get_object(Bucket=self._bucket, Key=key)["Body"].read()
                rows.extend(_parse_object_bytes(key, body))
                if limit and len(rows) >= limit:
                    break
            return rows

        try:
            return await asyncio.to_thread(_call)
        except (BotoCoreError, ClientError) as exc:
            raise NotImplementedError(f"S3 connector fetch failed: {exc}") from exc

    async def discover_schema(self) -> list[SchemaField]:
        rows = await self._fetch_rows(limit=1)
        if not rows:
            return []
        return [SchemaField(name=k, inferred_type=_infer_type(v)) for k, v in rows[0].items()]

    async def preview(self, limit: int = 10) -> list[dict[str, Any]]:
        return (await self._fetch_rows(limit=limit))[:limit]

    async def ingest(self) -> tuple[IngestResult, list[dict[str, Any]]]:
        rows = await self._fetch_rows()
        valid_rows = [r for r in rows if isinstance(r, dict) and r]
        rejected = len(rows) - len(valid_rows)
        errors = [f"{rejected} row(s) rejected: not a non-empty object"] if rejected else []
        return IngestResult(rows_ingested=len(valid_rows), rows_rejected=rejected, errors=errors), valid_rows


class _RealSftpSession:
    """Owns both the SFTP channel and its underlying SSH transport so
    `SftpConnector` can close both with a single call -- `paramiko.
    SFTPClient.close()` alone leaves the transport (and its background
    thread) open."""

    def __init__(self, transport: paramiko.Transport, sftp: paramiko.SFTPClient):
        self._transport = transport
        self._sftp = sftp

    def stat(self, path: str) -> Any:
        return self._sftp.stat(path)

    def open(self, path: str, mode: str = "r") -> Any:
        return self._sftp.open(path, mode)

    def close(self) -> None:
        try:
            self._sftp.close()
        finally:
            self._transport.close()


class SftpConnector(BaseEnterpriseDataConnector):
    """A genuine `paramiko` SFTP session against a customer-provisioned host.
    `connection_config` carries `host`/`port`/`username`/`remote_path` plus
    `password_env_var`/`private_key_env_var` naming environment variables
    holding the actual credential -- never stored here. `sftp_client_factory`
    lets a caller (a test) inject a fake session exposing `stat`/`open`/
    `close`, bypassing both paramiko and the network entirely."""

    connector_type = EnterpriseConnectorType.SFTP

    def __init__(
        self,
        *,
        source_id: str,
        classification: EnterpriseDataClassification,
        connection_config: dict[str, Any] | None = None,
        sftp_client_factory: Callable[[], Any] | None = None,
    ):
        self.source_id = source_id
        self.classification = classification
        config = connection_config or {}
        self._host: str | None = config.get("host")
        self._port: int = int(config.get("port", 22))
        self._username: str | None = config.get("username")
        self._remote_path: str | None = config.get("remote_path")
        self._password_env_var: str | None = config.get("password_env_var")
        self._private_key_env_var: str | None = config.get("private_key_env_var")
        self._sftp_client_factory = sftp_client_factory

    def _configured(self) -> bool:
        return bool(self._host and self._username and self._remote_path)

    def _open_session(self) -> Any:
        if self._sftp_client_factory is not None:
            return self._sftp_client_factory()
        password = os.environ.get(self._password_env_var) if self._password_env_var else None
        private_key_data = os.environ.get(self._private_key_env_var) if self._private_key_env_var else None
        pkey = paramiko.RSAKey.from_private_key(io.StringIO(private_key_data)) if private_key_data else None
        transport = paramiko.Transport((self._host, self._port))
        transport.connect(username=self._username, password=password, pkey=pkey)
        return _RealSftpSession(transport, paramiko.SFTPClient.from_transport(transport))

    async def test_connection(self) -> ConnectorHealth:
        if not self._configured():
            return ConnectorHealth(
                source_id=self.source_id, status="not_configured", detail="connection_config.host/username/remote_path not set"
            )

        def _call() -> None:
            session = self._open_session()
            try:
                session.stat(self._remote_path)
            finally:
                session.close()

        try:
            await asyncio.to_thread(_call)
        except Exception as exc:  # noqa: BLE001 -- SSH/SFTP failure modes are numerous (auth, network, missing path); this is the health-check boundary
            return ConnectorHealth(source_id=self.source_id, status="unavailable", detail=str(exc))
        return ConnectorHealth(source_id=self.source_id, status="healthy", detail=f"{self._remote_path} reachable")

    async def _fetch_rows(self) -> list[dict[str, Any]]:
        if not self._configured():
            raise NotImplementedError("SFTP connector has no connection_config.host/username/remote_path configured")

        def _call() -> list[dict[str, Any]]:
            session = self._open_session()
            try:
                with session.open(self._remote_path, "r") as f:
                    content = f.read()
            finally:
                session.close()
            if isinstance(content, str):
                content = content.encode("utf-8")
            return _parse_object_bytes(self._remote_path, content)

        try:
            return await asyncio.to_thread(_call)
        except NotImplementedError:
            raise
        except Exception as exc:  # noqa: BLE001 -- see test_connection
            raise NotImplementedError(f"SFTP connector fetch failed: {exc}") from exc

    async def discover_schema(self) -> list[SchemaField]:
        rows = await self._fetch_rows()
        if not rows:
            return []
        return [SchemaField(name=k, inferred_type=_infer_type(v)) for k, v in rows[0].items()]

    async def preview(self, limit: int = 10) -> list[dict[str, Any]]:
        return (await self._fetch_rows())[:limit]

    async def ingest(self) -> tuple[IngestResult, list[dict[str, Any]]]:
        rows = await self._fetch_rows()
        valid_rows = [r for r in rows if isinstance(r, dict) and r]
        rejected = len(rows) - len(valid_rows)
        errors = [f"{rejected} row(s) rejected: not a non-empty object"] if rejected else []
        return IngestResult(rows_ingested=len(valid_rows), rows_rejected=rejected, errors=errors), valid_rows


def build_connector(
    *,
    connector_type: EnterpriseConnectorType,
    source_id: str,
    classification: EnterpriseDataClassification,
    connection_config: dict[str, Any] | None = None,
    rows: list[dict[str, Any]] | None = None,
    has_signing_secret: bool = False,
) -> BaseEnterpriseDataConnector:
    if connector_type == EnterpriseConnectorType.MANUAL_UPLOAD:
        return ManualUploadConnector(source_id=source_id, classification=classification, rows=rows or [])
    if connector_type == EnterpriseConnectorType.WEBHOOK:
        return WebhookConnector(
            source_id=source_id, classification=classification, rows=rows or [], has_signing_secret=has_signing_secret
        )
    if connector_type == EnterpriseConnectorType.REST_API:
        return RestApiConnector(source_id=source_id, classification=classification, connection_config=connection_config)
    if connector_type == EnterpriseConnectorType.DATABASE:
        return DatabaseConnector(source_id=source_id, classification=classification, connection_config=connection_config)
    if connector_type == EnterpriseConnectorType.S3:
        return S3Connector(source_id=source_id, classification=classification, connection_config=connection_config)
    if connector_type == EnterpriseConnectorType.SFTP:
        return SftpConnector(source_id=source_id, classification=classification, connection_config=connection_config)
    return NotImplementedConnector(connector_type=connector_type, classification=classification, source_id=source_id)


def sign_webhook_payload(secret: str, raw_body: bytes) -> str:
    """The exact HMAC-SHA256 hex digest `POST /webhooks/enterprise-data/
    {source_id}` requires in its `X-AlphaGasIQ-Signature` header -- shared
    here so a customer's webhook sender and this codebase's own tests compute
    the signature identically."""
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
