from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid_str() -> str:
    return str(uuid.uuid4())


class TradeIdeaRow(Base):
    __tablename__ = "trade_ideas"

    trade_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    strategy: Mapped[str] = mapped_column(String, nullable=False)
    instrument: Mapped[str] = mapped_column(String, nullable=False)
    instrument_type: Mapped[str] = mapped_column(String, nullable=False)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    entry: Mapped[float] = mapped_column(Float, nullable=False)
    target: Mapped[float] = mapped_column(Float, nullable=False)
    stop_or_invalidation: Mapped[float] = mapped_column(Float, nullable=False)
    time_horizon: Mapped[str] = mapped_column(String, nullable=False)
    expected_return: Mapped[float] = mapped_column(Float, nullable=False)
    expected_loss: Mapped[float] = mapped_column(Float, nullable=False)
    probability_success: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    thesis: Mapped[str] = mapped_column(String, nullable=False)
    catalysts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    risks: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    invalidation_conditions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    supporting_data: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source_citations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Quant/post-trade unification: the PriceForecast attached at trade creation,
    # stored as its raw dict so it round-trips without needing its own table.
    forecast: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class CommitteeDecisionRow(Base):
    __tablename__ = "committee_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    original_trade_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trade_ideas.trade_id"), nullable=False
    )
    original_trade: Mapped[dict] = mapped_column(JSON, nullable=False)
    bull_case: Mapped[str] = mapped_column(String, nullable=False)
    bear_case: Mapped[str] = mapped_column(String, nullable=False)
    skeptic_case: Mapped[str] = mapped_column(String, nullable=False)
    data_quality_assessment: Mapped[str] = mapped_column(String, nullable=False)
    portfolio_effect: Mapped[str] = mapped_column(String, nullable=False)
    consensus_score: Mapped[float] = mapped_column(Float, nullable=False)
    unresolved_questions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    recommended_action: Mapped[str] = mapped_column(String, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class RiskCheckRow(Base):
    __tablename__ = "risk_checks"

    check_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    trade_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trade_ideas.trade_id"), nullable=False
    )
    verdict: Mapped[str] = mapped_column(String, nullable=False)
    rule_results: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    governor_version: Mapped[str] = mapped_column(String, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class ApprovalRow(Base):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    trade_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trade_ideas.trade_id"), nullable=False
    )
    state: Mapped[str] = mapped_column(String, nullable=False)
    actions: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    current_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class DecisionJournalRow(Base):
    __tablename__ = "decision_journal"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    trade_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trade_ideas.trade_id"), nullable=False
    )
    entry: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class PostTradeAnalysisRow(Base):
    __tablename__ = "post_trade_analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    trade_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("trade_ideas.trade_id"), nullable=False
    )
    expected_outcome: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    actual_outcome: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    forecast_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    thesis_accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    timing_accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    risk_accuracy: Mapped[float] = mapped_column(Float, nullable=False)
    model_contribution: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    unexpected_events: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    lessons: Mapped[str] = mapped_column(String, nullable=False, default="")
    quadrant: Mapped[str] = mapped_column(String, nullable=False)
    quant_model_type: Mapped[str | None] = mapped_column(String, nullable=True)
    quant_model_version: Mapped[str | None] = mapped_column(String, nullable=True)
    quant_predicted_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    quant_forecast_error: Mapped[float | None] = mapped_column(Float, nullable=True)
    quant_up_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class ContactInquiryRow(Base):
    """A general business inquiry submitted via the public /contact page. This is
    deliberately NOT part of the account-provisioning system: it never creates a
    User, Organization, or MagicLinkToken row, and nothing reads this table to grant
    platform access. See docs/access-model.md "No Self-Registration"."""

    __tablename__ = "contact_inquiries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    first_name: Mapped[str] = mapped_column(String, nullable=False)
    last_name: Mapped[str] = mapped_column(String, nullable=False)
    business_email: Mapped[str] = mapped_column(String, nullable=False)
    company_name: Mapped[str] = mapped_column(String, nullable=False)
    job_title: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    inquiry_type: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class OrganizationRow(Base):
    """An institutional client account. Users belong to exactly one Organization,
    looked up by name or created inline during admin user creation — see
    docs/access-model.md §14 "Organization Management"."""

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    website: Mapped[str | None] = mapped_column(String, nullable=True)
    industry: Mapped[str | None] = mapped_column(String, nullable=True)
    company_type: Mapped[str | None] = mapped_column(String, nullable=True)
    country: Mapped[str | None] = mapped_column(String, nullable=True)
    state_region: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ACTIVE")
    billing_plan: Mapped[str | None] = mapped_column(String, nullable=True)
    account_owner: Mapped[str | None] = mapped_column(String, nullable=True)
    primary_contact: Mapped[str | None] = mapped_column(String, nullable=True)
    feature_package: Mapped[str | None] = mapped_column(String, nullable=True)
    data_entitlements: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class RoleRow(Base):
    """One of the 8 fixed roles seeded at startup (`SqlAppRepository.seed_rbac_defaults`)
    — see docs/access-model.md §5. Custom roles are structurally possible (this is a
    DB row, not a hardcoded enum) but none are created by this codebase."""

    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    name: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)


class PermissionRow(Base):
    """A single fine-grained permission key (e.g. `admin.users.create`), seeded at
    startup from the fixed list in docs/access-model.md §5. Enforcement of these via
    `require_permission(...)` FastAPI dependencies lands in Milestone 4 — today only
    `require_role` (apps/api/api_app/auth.py) is enforced at the router layer."""

    __tablename__ = "permissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)


class RolePermissionRow(Base):
    __tablename__ = "role_permissions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    role_id: Mapped[str] = mapped_column(String(36), ForeignKey("roles.id"), nullable=False)
    permission_id: Mapped[str] = mapped_column(String(36), ForeignKey("permissions.id"), nullable=False)


class UserRow(Base):
    """An AlphaGasIQ account. Only ever created by an authenticated administrator via
    `POST /admin/users` (`apps/api/api_app/routers/admin_users.py`) — there is no
    unauthenticated code path that can insert a row here. See docs/access-model.md."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    first_name: Mapped[str] = mapped_column(String, nullable=False)
    last_name: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=False)
    job_title: Mapped[str | None] = mapped_column(String, nullable=True)
    department: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    country: Mapped[str | None] = mapped_column(String, nullable=True)
    state_region: Mapped[str | None] = mapped_column(String, nullable=True)
    primary_use_case: Mapped[str | None] = mapped_column(String, nullable=True)
    market_experience: Mapped[str | None] = mapped_column(String, nullable=True)
    role_id: Mapped[str] = mapped_column(String(36), ForeignKey("roles.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="INVITED")
    expiration_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MagicLinkTokenRow(Base):
    """A single-use passwordless-login token (docs/access-model.md §3, spec §63). Only
    `token_hash` (sha256 of the raw token) is ever stored — the raw token exists only
    in the outbound email URL and this table can never be used to recover it."""

    __tablename__ = "magic_link_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    requested_ip: Mapped[str | None] = mapped_column(String, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String, nullable=True)


class SessionRow(Base):
    """A server-revocable authenticated session (docs/access-model.md §4). Only
    magic-link-issued JWTs carry a `sid` claim pointing at one of these rows — the
    dev-mode/OIDC login paths remain stateless JWTs with no `Session` row, unchanged
    from before this milestone."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class FeatureRow(Base):
    """A gateable unit of platform functionality (docs/access-model.md §5, spec §24) —
    e.g. "Chief Trading Agent Chat" or "Data Export". Seeded at startup alongside the
    RBAC data; `security_sensitive=True` features get deny-only user-level overrides
    (a user override can never grant access beyond what role+org already allow), all
    others get full override (can grant or deny), per spec §24's "deny-overrides for
    security-sensitive features"."""

    __tablename__ = "features"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    security_sensitive: Mapped[bool] = mapped_column(nullable=False, default=False)
    globally_enabled: Mapped[bool] = mapped_column(nullable=False, default=True)


class RoleFeatureEntitlementRow(Base):
    """Role-level feature grant. Deny-by-default: a role only has a feature if an
    explicit row here says `enabled=True` — there is no implicit "all roles get
    everything" fallback."""

    __tablename__ = "role_feature_entitlements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    role_id: Mapped[str] = mapped_column(String(36), ForeignKey("roles.id"), nullable=False)
    feature_id: Mapped[str] = mapped_column(String(36), ForeignKey("features.id"), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)


class OrganizationFeatureEntitlementRow(Base):
    """Organization-level feature restriction/confirmation. Allow-by-default: absence
    of a row means the organization's plan does not additionally restrict a feature
    the user's role already grants; an explicit `enabled=False` row is how a client's
    plan excludes a feature regardless of role."""

    __tablename__ = "organization_feature_entitlements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=False)
    feature_id: Mapped[str] = mapped_column(String(36), ForeignKey("features.id"), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)


class UserFeatureOverrideRow(Base):
    """Per-user feature override. For a `security_sensitive` feature this can only
    narrow access (an `enabled=True` override is ignored if role/org already deny the
    feature); for any other feature it can both grant and deny regardless of role/org
    — see `apps/api/api_app/entitlements.py::get_effective_features` for the exact
    algorithm."""

    __tablename__ = "user_feature_overrides"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    feature_id: Mapped[str] = mapped_column(String(36), ForeignKey("features.id"), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)


class ChatConversationRow(Base):
    """A persisted Chief Trading Agent Chat conversation (docs/access-model.md §6,
    spec §29). `id` is shared with the in-memory `ChatSession.id` the router already
    returns — this table is a write-through durability layer behind that existing
    response contract, not a replacement for it (mirrors how `AppState`'s other
    in-memory dicts write through to `SqlAppRepository` — see `state.py`)."""

    __tablename__ = "chat_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False)
    organization_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("organizations.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class ChatMessageRow(Base):
    """One turn of a `ChatConversationRow`. Deliberately has no column for a private
    chain-of-thought — only the user's message, the assistant's final response, and
    metadata about how that response was produced (spec §29: "Do not persist private
    chain-of-thought")."""

    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("chat_conversations.id"), nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    citations: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    freshness: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    tool_used: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    permissions_context: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class SystemSettingRow(Base):
    """A single named, admin-editable non-sensitive platform setting (spec §38 —
    Platform Name, Support Email, Default Timezone, etc.). Every change is versioned/
    timestamped/reversible via `SystemSettingHistoryRow` — see
    `SqlAppRepository.set_system_setting`."""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    updated_by: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class SystemSettingHistoryRow(Base):
    """Append-only history of every prior value a `SystemSettingRow` held — spec §38
    "System information changes must be: Versioned, Timestamped, Audited, Reversible
    where practical". A full cross-cutting `AuditEvent` table (spec §54-55) lands in
    Milestone 10; this dedicated history table covers system-setting changes now."""

    __tablename__ = "system_setting_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    key: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    changed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class DataFeedConfigRow(Base):
    """Admin-configurable state for one registered `data_sdk.BaseDataProvider`
    (spec §36 "Data Feed Administration"). Deliberately holds no credential/secret
    field — every provider's API key/token is environment-provisioned
    (`packages/config/config/settings.py`) and never touches this table or the API
    layer at all, which is the strongest possible reading of spec §36's "Credentials
    must never be redisplayed after entry" (they are never *displayed*, or even
    *enterable*, through this admin surface in the first place)."""

    __tablename__ = "data_feed_configs"

    provider_id: Mapped[str] = mapped_column(String, primary_key=True)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    paused: Mapped[bool] = mapped_column(nullable=False, default=False)
    polling_frequency_seconds: Mapped[int | None] = mapped_column(nullable=True)
    freshness_threshold_seconds: Mapped[int | None] = mapped_column(nullable=True)
    priority: Mapped[int] = mapped_column(nullable=False, default=100)
    fallback_provider_id: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class DataFeedEventRow(Base):
    """An ingestion-log entry (spec §36 "View ingestion logs" / "Review errors") —
    written by the admin "Test Connection" and "Trigger Manual Refresh" actions."""

    __tablename__ = "data_feed_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    provider_id: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)  # test_connection | manual_refresh
    status: Mapped[str] = mapped_column(String, nullable=False)  # success | error
    detail: Mapped[str] = mapped_column(String, nullable=False, default="")
    records_received: Mapped[int | None] = mapped_column(nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class AgentConfigRow(Base):
    """Admin-editable operational state for one implemented, LLM-driven agent seat
    (spec §39, `docs/agent-governance.md` §2-3) -- enable/pause/disable and the
    confidence/alert/escalation thresholds an administrator can tune. Seeded one row
    per currently-implemented `AgentType` (`apps/api/api_app/agent_catalog.py`), minus
    `RISK_GOVERNOR`, which has no admin-settable state here (see that module's
    `administrable` flag and `docs/agent-governance.md` §1)."""

    __tablename__ = "agent_configs"

    agent_type: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ACTIVE")
    confidence_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    alert_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    escalation_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class AgentVersionRow(Base):
    """One version of an agent's configuration (spec §§40-41, `docs/agent-governance.md`
    §4) -- model/prompt/tool/threshold config, its lifecycle status, and evaluation
    results. **A production agent definition is never overwritten**: every change to an
    agent's instructions, model, or thresholds creates a new row here rather than
    mutating an existing one, and promoting a version never means the agent's Python
    class is regenerated or replaced -- it means the runtime *would* read its config
    from the `PRODUCTION`-status row (wiring that read path per-agent into
    `services/agents` is real follow-up work, tracked honestly rather than assumed).

    Status lifecycle (enforced in `repository.py`, never skippable):
    DRAFT -> TESTING -> APPROVED -> PRODUCTION -> (RETIRED | ROLLED_BACK). No transition
    may skip a step -- "no prompt change may automatically bypass evaluation" (spec
    §41). Promoting a new PRODUCTION version automatically retires the agent's prior
    PRODUCTION row, so at most one PRODUCTION version per agent_type exists at a time.
    """

    __tablename__ = "agent_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    agent_type: Mapped[str] = mapped_column(String, nullable=False)
    version: Mapped[str] = mapped_column(String, nullable=False)
    model_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String, nullable=True)
    system_instructions: Mapped[str | None] = mapped_column(String, nullable=True)
    tool_configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    data_sources: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    execution_settings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    thresholds: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String, nullable=False, default="DRAFT")
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    evaluation_results: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deployment_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)


class RiskLimitsRow(Base):
    __tablename__ = "risk_limits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid_str)
    max_position_size: Mapped[float] = mapped_column(Float, nullable=False)
    max_risk_per_trade: Mapped[float] = mapped_column(Float, nullable=False)
    max_daily_loss: Mapped[float] = mapped_column(Float, nullable=False)
    max_drawdown: Mapped[float] = mapped_column(Float, nullable=False)
    max_portfolio_var: Mapped[float] = mapped_column(Float, nullable=False)
    max_sector_exposure: Mapped[float] = mapped_column(Float, nullable=False)
    max_contract_exposure: Mapped[float] = mapped_column(Float, nullable=False)
    max_correlated_exposure: Mapped[float] = mapped_column(Float, nullable=False)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    effective_to: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    set_by_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
