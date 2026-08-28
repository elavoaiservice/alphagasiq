"""Enterprise Data Platform schemas (docs/alpha-intelligence.md section 11,
Milestone 8). Lets an authorized enterprise customer combine their own
proprietary data with the Alpha Intelligence Layer. Nothing in this module
talks to a database, an LLM, or the network -- a pure data contract, exactly
like every other schema in this package.

`Workspace` is new: a grouping inside an `Organization`, layered on top of the
existing `Organization`/`Role`/`Permission`/`Feature` tables rather than
replacing them. `EnterpriseDataClassification` is a **security-tier**
classification, deliberately a new enum rather than reusing the existing
`DataClassification` (a **data-provenance** tag on ingested observations) --
see docs/alpha-intelligence.md section 2 for why the two must not collide.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EnterpriseDataClassification(str, Enum):
    """Security-tier classification (docs/alpha-intelligence.md section 11.2) --
    distinct from `DataClassification`'s provenance tag. Access rules combine
    this with organization/workspace/role/permission/feature/dataset/agent
    entitlements."""

    PUBLIC = "PUBLIC"
    LICENSED_MARKET_DATA = "LICENSED_MARKET_DATA"
    ALPHAGASIQ_PROPRIETARY = "ALPHAGASIQ_PROPRIETARY"
    CUSTOMER_CONFIDENTIAL = "CUSTOMER_CONFIDENTIAL"
    CUSTOMER_RESTRICTED = "CUSTOMER_RESTRICTED"
    CUSTOMER_POSITION_DATA = "CUSTOMER_POSITION_DATA"
    CUSTOMER_RISK_DATA = "CUSTOMER_RISK_DATA"
    SIMULATED = "SIMULATED"


class EnterpriseDataDomain(str, Enum):
    """The canonical energy data model domains every enterprise dataset
    normalizes into (docs/alpha-intelligence.md section 11.4), the same
    discipline `ObservationDraft` already establishes for market data."""

    MARKET_PRICE = "MARKET_PRICE"
    PRODUCTION = "PRODUCTION"
    DEMAND = "DEMAND"
    WEATHER = "WEATHER"
    STORAGE = "STORAGE"
    PIPELINE = "PIPELINE"
    TRANSPORTATION = "TRANSPORTATION"
    LNG = "LNG"
    POWER = "POWER"
    NEWS_EVENT = "NEWS_EVENT"
    POSITION = "POSITION"
    PORTFOLIO = "PORTFOLIO"
    HEDGE = "HEDGE"
    CONTRACT = "CONTRACT"
    RISK = "RISK"
    FORECAST = "FORECAST"
    SCENARIO = "SCENARIO"
    ASSET = "ASSET"
    FACILITY = "FACILITY"
    NODE = "NODE"
    FLOW = "FLOW"


class EnterpriseConnectorType(str, Enum):
    """Connector shapes an enterprise data source can declare
    (docs/alpha-intelligence.md section 11.3). Milestone 8 implements exactly
    one (`MANUAL_UPLOAD`) end-to-end -- the only shape genuinely operable
    without external credentials this codebase doesn't have -- the same
    "must have a usable path with zero paid subscriptions" discipline
    `BaseDataProvider`'s `Mock*Provider` siblings already establish. The rest
    are declared on the enum for forward-compatibility (an admin can register a
    source of that type) but have no connector implementation yet; attempting
    to use one raises `NotImplementedError`, honestly, rather than silently
    behaving like `MANUAL_UPLOAD`."""

    MANUAL_UPLOAD = "MANUAL_UPLOAD"
    REST_API = "REST_API"
    SFTP = "SFTP"
    DATABASE = "DATABASE"
    S3 = "S3"
    WEBHOOK = "WEBHOOK"


class EnterpriseSourceStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ERROR = "ERROR"


class Workspace(BaseModel):
    """A grouping inside an `Organization` (docs/alpha-intelligence.md section
    11.1) -- e.g. a trading desk or a business unit -- that enterprise data
    sources, datasets, and entitlements can be scoped to."""

    id: UUID = Field(default_factory=uuid4)
    organization_id: str
    name: str
    description: str = ""
    created_by: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class EnterpriseDataSource(BaseModel):
    """An admin-registered connection to a customer's proprietary data
    (docs/alpha-intelligence.md section 11.3/11.4). Deliberately carries no
    credential/secret field -- exactly the same posture `DataFeedConfigRow`
    already takes for the built-in public/licensed connectors: real secrets are
    environment-provisioned and never touch this object or the admin API."""

    id: UUID = Field(default_factory=uuid4)
    organization_id: str
    workspace_id: UUID | None = None
    name: str
    connector_type: EnterpriseConnectorType
    classification: EnterpriseDataClassification
    status: EnterpriseSourceStatus = EnterpriseSourceStatus.DRAFT
    description: str = ""
    connection_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Non-secret connector configuration only (e.g. a bucket name, "
        "an endpoint URL) -- never a credential value.",
    )
    created_by: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class EnterpriseDataset(BaseModel):
    """One registered dataset within an `EnterpriseDataSource`, normalized into
    a canonical `EnterpriseDataDomain`."""

    id: UUID = Field(default_factory=uuid4)
    source_id: UUID
    organization_id: str
    name: str
    domain: EnterpriseDataDomain
    classification: EnterpriseDataClassification
    schema_summary: dict[str, str] = Field(
        default_factory=dict, description="Field name -> inferred type, from discover_schema()."
    )
    row_count: int = 0
    last_synced_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class EnterpriseEntitlementPrincipalType(str, Enum):
    """Who a dataset entitlement is granted to. `AGENT` is the
    `AgentDataEntitlement` concept from docs/alpha-intelligence.md section
    11.1 -- deliberately unified into one entitlement table with `USER`/
    `ROLE`/`WORKSPACE` rather than a structurally-identical parallel table."""

    USER = "USER"
    ROLE = "ROLE"
    WORKSPACE = "WORKSPACE"
    AGENT = "AGENT"


class EnterpriseDataEntitlement(BaseModel):
    """Grants a principal (a user, a role, an entire workspace, or -- per
    docs/alpha-intelligence.md's `AgentDataEntitlement` -- a specific agent
    type) read access to one dataset. Recording this grant is Milestone 8's
    scope; per-agent runtime enforcement inside each fundamental/quant agent
    (no agent reads enterprise datasets today) remains future work, honestly
    undocumented as built until it exists."""

    id: UUID = Field(default_factory=uuid4)
    dataset_id: UUID
    principal_type: EnterpriseEntitlementPrincipalType
    principal_id: str
    granted_by: str | None = None
    granted_at: datetime = Field(default_factory=datetime.utcnow)


class ModelRoutingPolicy(BaseModel):
    """Tenant-isolation retrofit (docs/alpha-intelligence.md section 11.1,
    Milestone 9): governs whether content of a given `EnterpriseDataClassification`
    may be sent to an *external* LLM provider for a given organization, and if so
    which provider/region/logging posture applies. `organization_id=None` is the
    platform default policy, consulted when an organization has registered no
    override for that classification -- the same nullable-organization_id
    "platform-wide unless overridden" convention every Alpha*/enterprise table
    already uses. Enforced by `enterprise_data_service.model_routing.
    ModelRoutingEngine` / `agent_sdk.llm.PolicyGatedLLMProvider`; see those modules'
    docstrings for why no agent call site threads a classification through this
    yet (no agent consumes classified enterprise data in its prompts today -- that
    integration is Milestone 10's job)."""

    id: UUID = Field(default_factory=uuid4)
    organization_id: str | None = None
    data_classification: EnterpriseDataClassification
    allow_external_llm_processing: bool
    allowed_provider: str | None = Field(
        default=None, description="e.g. 'anthropic' -- None means no restriction beyond the allow/deny gate."
    )
    allowed_region: str | None = None
    logging_allowed: bool = True
    created_by: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RetentionPolicy(BaseModel):
    """Tenant-isolation retrofit (docs/alpha-intelligence.md section 11.1,
    Milestone 9): how many days a given `EnterpriseDataClassification`'s data may
    be retained for an organization before `apply_retention_policy` purges it.
    Same `organization_id=None` platform-default convention as
    `ModelRoutingPolicy`. `retention_days=None` means retain indefinitely (no
    purge) -- an explicit choice, not an oversight, since not every
    classification needs a mandatory expiry."""

    id: UUID = Field(default_factory=uuid4)
    organization_id: str | None = None
    data_classification: EnterpriseDataClassification
    retention_days: int | None = None
    created_by: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class EnterpriseOpportunityType(str, Enum):
    """The two opportunity shapes `EnterpriseOpportunityEngine`
    (docs/alpha-intelligence.md section 11.7, Milestone 10) detects -- a
    deliberately small, documented set, not an open-ended taxonomy."""

    HEDGE_MISALIGNED_POSITION = "HEDGE_MISALIGNED_POSITION"
    NEW_POSITION_HIGH_CONVICTION_SIGNAL = "NEW_POSITION_HIGH_CONVICTION_SIGNAL"


class EnterpriseOpportunityStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class EnterpriseOpportunity(BaseModel):
    """A candidate opportunity `EnterpriseOpportunityEngine` drafted by
    cross-referencing an organization's own proprietary position data against
    the Alpha Intelligence Layer's signals/consensus (docs/alpha-intelligence.md
    section 11.7, Milestone 10) -- always human-reviewed, exactly the same
    "AI-drafted but never an automatic feedback loop" posture
    `LessonProposal` already establishes for AlphaMemory(TM); nothing here is
    ever auto-executed into a trade or position change. Unlike every other
    Alpha*/enterprise table, `organization_id` is **required**, not nullable --
    an opportunity is inherently derived from one organization's own
    proprietary position data, so a platform-wide opportunity is not a
    meaningful concept the way a platform-wide `Signal` is."""

    id: UUID = Field(default_factory=uuid4)
    organization_id: str
    workspace_id: str | None = None
    opportunity_type: EnterpriseOpportunityType
    market: str
    title: str
    summary: str
    confidence: float = Field(ge=0, le=1)
    supporting_signal_ids: list[str] = Field(default_factory=list)
    supporting_consensus_id: str | None = None
    related_dataset_id: str | None = None
    related_record_id: str | None = None
    status: EnterpriseOpportunityStatus = EnterpriseOpportunityStatus.PENDING
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
