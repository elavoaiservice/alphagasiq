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
