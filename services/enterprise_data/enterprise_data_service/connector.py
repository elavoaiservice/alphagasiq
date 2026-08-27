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

Only `MANUAL_UPLOAD` (`ManualUploadConnector`) is implemented end-to-end this
milestone -- the one connector shape genuinely operable without external
credentials this codebase doesn't have, the same "must have a usable path with
zero paid subscriptions" discipline every `Mock*Provider` already establishes.
`REST_API`/`SFTP`/`DATABASE`/`S3`/`WEBHOOK` are declared on
`EnterpriseConnectorType` for forward-compatibility only; `build_connector()`
returns a `NotImplementedConnector` for those, which reports `not_configured`
honestly rather than silently behaving like `MANUAL_UPLOAD`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from schemas import EnterpriseConnectorType, EnterpriseDataClassification


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
    """Placeholder for a connector type declared on `EnterpriseConnectorType`
    but not yet built. Reports `not_configured` honestly, mirroring
    `data_sdk.provider.NotImplementedProvider`'s exact same posture."""

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


class ManualUploadConnector(BaseEnterpriseDataConnector):
    """The one connector type Milestone 8 implements end-to-end: an
    administrator supplies already-parsed tabular rows (e.g. an uploaded CSV,
    parsed before reaching this class) -- no external network call, no
    credential, genuinely usable with zero paid subscriptions."""

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


def build_connector(
    *,
    connector_type: EnterpriseConnectorType,
    source_id: str,
    classification: EnterpriseDataClassification,
    rows: list[dict[str, Any]] | None = None,
) -> BaseEnterpriseDataConnector:
    if connector_type == EnterpriseConnectorType.MANUAL_UPLOAD:
        return ManualUploadConnector(source_id=source_id, classification=classification, rows=rows or [])
    return NotImplementedConnector(connector_type=connector_type, classification=classification, source_id=source_id)
