from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from schemas import (
    InvestmentCommitteeDecision,
    PostTradeAnalysis,
    PriceForecast,
    RiskCheckResult,
    RiskLimits,
    TradeIdea,
)

from .engine import build_engine, build_sessionmaker
from .models import (
    ApprovalRow,
    Base,
    CommitteeDecisionRow,
    ContactInquiryRow,
    DecisionJournalRow,
    OrganizationRow,
    PermissionRow,
    PostTradeAnalysisRow,
    RiskCheckRow,
    RiskLimitsRow,
    RolePermissionRow,
    RoleRow,
    TradeIdeaRow,
    UserRow,
)

# The 8 fixed roles from docs/access-model.md §5 (spec §23). Roles are DB rows (not a
# hardcoded enum) so custom roles remain structurally possible, but only these 8 are
# ever seeded.
_ROLE_NAMES = [
    "SUPER_ADMIN",
    "ADMIN",
    "TRADER",
    "RISK_MANAGER",
    "RESEARCHER",
    "EXECUTIVE",
    "VIEWER",
    "API_USER",
]

# The full permission-key list from docs/access-model.md §5 (spec §23), verbatim.
_PERMISSION_KEYS = [
    "dashboard.view",
    "market_data.view",
    "weather.view",
    "storage.view",
    "pipeline.view",
    "lng.view",
    "power.view",
    "news.view",
    "trading_recommendations.view",
    "trading_recommendations.challenge",
    "chief_agent.chat",
    "portfolio.view",
    "portfolio.manage",
    "risk.view",
    "risk.manage",
    "paper_trading.view",
    "paper_trading.execute",
    "data_export",
    "api_access",
    "admin.dashboard",
    "admin.users.view",
    "admin.users.create",
    "admin.users.edit",
    "admin.users.suspend",
    "admin.users.revoke",
    "admin.users.permissions",
    "admin.users.features",
    "admin.users.sessions",
    "admin.organizations",
    "admin.data_feeds",
    "admin.system_settings",
    "admin.agent_management",
    "admin.agent_optimization",
    "admin.model_management",
    "admin.audit_logs",
    "admin.feature_management",
    "admin.risk_settings",
]

# Permissions reserved for SUPER_ADMIN: the system-level/risk/model/agent-optimization
# controls the spec keeps behind the strictest boundary (docs/risk-framework.md — the
# Risk Governor and agent-optimization approval chain are never reachable by a lesser
# role). ADMIN gets every other permission, including day-to-day user/org/feature/
# data-feed/agent administration.
_SUPER_ADMIN_ONLY_PERMISSIONS = {
    "admin.system_settings",
    "admin.risk_settings",
    "admin.agent_optimization",
    "admin.model_management",
}

# Default role -> permission grants seeded at startup. This is the initial, reviewable
# default (docs/access-model.md §5); full entitlement enforcement (require_permission
# dependencies, Feature/*Entitlement tables) lands in Milestone 4, at which point this
# mapping becomes admin-editable rather than a fixed seed.
_ROLE_PERMISSIONS: dict[str, list[str]] = {
    "SUPER_ADMIN": list(_PERMISSION_KEYS),
    "ADMIN": [p for p in _PERMISSION_KEYS if p not in _SUPER_ADMIN_ONLY_PERMISSIONS],
    "TRADER": [
        "dashboard.view",
        "market_data.view",
        "weather.view",
        "storage.view",
        "pipeline.view",
        "lng.view",
        "power.view",
        "news.view",
        "trading_recommendations.view",
        "trading_recommendations.challenge",
        "chief_agent.chat",
        "portfolio.view",
        "portfolio.manage",
        "paper_trading.view",
        "paper_trading.execute",
    ],
    "RISK_MANAGER": [
        "dashboard.view",
        "market_data.view",
        "weather.view",
        "storage.view",
        "pipeline.view",
        "lng.view",
        "power.view",
        "news.view",
        "trading_recommendations.view",
        "chief_agent.chat",
        "portfolio.view",
        "risk.view",
        "risk.manage",
        "paper_trading.view",
    ],
    "RESEARCHER": [
        "dashboard.view",
        "market_data.view",
        "weather.view",
        "storage.view",
        "pipeline.view",
        "lng.view",
        "power.view",
        "news.view",
        "trading_recommendations.view",
        "trading_recommendations.challenge",
        "chief_agent.chat",
        "portfolio.view",
        "risk.view",
        "data_export",
    ],
    "EXECUTIVE": [
        "dashboard.view",
        "market_data.view",
        "weather.view",
        "storage.view",
        "pipeline.view",
        "lng.view",
        "power.view",
        "news.view",
        "trading_recommendations.view",
        "portfolio.view",
        "risk.view",
        "chief_agent.chat",
    ],
    "VIEWER": [
        "dashboard.view",
        "market_data.view",
        "weather.view",
        "storage.view",
        "pipeline.view",
        "lng.view",
        "power.view",
        "news.view",
        "trading_recommendations.view",
    ],
    "API_USER": [
        "market_data.view",
        "weather.view",
        "storage.view",
        "pipeline.view",
        "lng.view",
        "power.view",
        "news.view",
        "data_export",
        "api_access",
    ],
}


def _organization_to_dict(row: OrganizationRow) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "website": row.website,
        "industry": row.industry,
        "company_type": row.company_type,
        "country": row.country,
        "state_region": row.state_region,
        "status": row.status,
        "billing_plan": row.billing_plan,
        "account_owner": row.account_owner,
        "primary_contact": row.primary_contact,
        "feature_package": row.feature_package,
        "data_entitlements": row.data_entitlements,
        "notes": row.notes,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _role_to_dict(row: RoleRow) -> dict:
    return {"id": row.id, "name": row.name, "description": row.description}


def _user_to_dict(row: UserRow) -> dict:
    return {
        "id": row.id,
        "first_name": row.first_name,
        "last_name": row.last_name,
        "email": row.email,
        "organization_id": row.organization_id,
        "job_title": row.job_title,
        "department": row.department,
        "phone": row.phone,
        "country": row.country,
        "state_region": row.state_region,
        "primary_use_case": row.primary_use_case,
        "market_experience": row.market_experience,
        "role_id": row.role_id,
        "status": row.status,
        "expiration_at": row.expiration_at,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "activated_at": row.activated_at,
        "last_login_at": row.last_login_at,
    }


def _naive_utc(dt: datetime | None) -> datetime | None:
    """Normalizes to a naive UTC `datetime` before binding to a `DateTime` column.

    The schemas across this codebase mix naive (`datetime.utcnow()` defaults) and
    timezone-aware datetimes for what's conceptually the same "naive UTC" convention.
    sqlite silently tolerates that mix; `asyncpg`'s timestamp encoder does not — it
    raises `TypeError: can't subtract offset-naive and offset-aware datetimes` when an
    aware value reaches a `TIMESTAMP WITHOUT TIME ZONE` column, which real-Postgres
    validation of this repository surfaced.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class SqlAppRepository:
    """Durable, write-through persistence for `AppState`'s trading objects.

    `AppState` keeps its existing in-memory dicts as the router-facing read path (so
    no router code changes are needed); every mutation additionally writes through to
    this repository, and `hydrate()` reloads everything from the DB on boot so state
    survives a process restart. Deliberately decoupled from `apps/api` — it only knows
    about `schemas` types (safe: `packages/db` already depends on `alphagasiq-schemas`)
    plus plain primitives for the one app-local type (`Approval`), so `apps/api` maps
    to/from its own model at the call site instead of this package importing it.
    """

    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = build_engine(database_url)
        self.session_factory: async_sessionmaker = build_sessionmaker(self.engine)

    async def init_schema(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def seed_rbac_defaults(self) -> None:
        """Seeds the 8 fixed roles, the full permission-key list, and each role's
        default grants (see the module-level `_ROLE_NAMES`/`_PERMISSION_KEYS`/
        `_ROLE_PERMISSIONS` constants above). Idempotent — safe to call on every
        process boot; only inserts rows that don't already exist, so an admin who
        edits a role's grants in a later milestone won't have that edit reverted by
        the next restart re-running this seed."""
        async with self.session_factory() as session:
            existing_role_names = set((await session.execute(select(RoleRow.name))).scalars().all())
            for name in _ROLE_NAMES:
                if name not in existing_role_names:
                    session.add(RoleRow(name=name))

            existing_permission_keys = set((await session.execute(select(PermissionRow.key))).scalars().all())
            for key in _PERMISSION_KEYS:
                if key not in existing_permission_keys:
                    session.add(PermissionRow(key=key))

            await session.flush()

            role_id_by_name = {r.name: r.id for r in (await session.execute(select(RoleRow))).scalars().all()}
            permission_id_by_key = {
                p.key: p.id for p in (await session.execute(select(PermissionRow))).scalars().all()
            }
            existing_grants = {
                (rp.role_id, rp.permission_id)
                for rp in (await session.execute(select(RolePermissionRow))).scalars().all()
            }

            for role_name, permission_keys in _ROLE_PERMISSIONS.items():
                role_id = role_id_by_name[role_name]
                for key in permission_keys:
                    permission_id = permission_id_by_key[key]
                    if (role_id, permission_id) not in existing_grants:
                        session.add(RolePermissionRow(role_id=role_id, permission_id=permission_id))

            await session.commit()

    async def list_roles(self) -> list[dict]:
        async with self.session_factory() as session:
            rows = (await session.execute(select(RoleRow).order_by(RoleRow.name))).scalars().all()
        return [_role_to_dict(r) for r in rows]

    async def get_role_by_name(self, name: str) -> dict | None:
        async with self.session_factory() as session:
            row = (await session.execute(select(RoleRow).where(RoleRow.name == name))).scalar_one_or_none()
        return _role_to_dict(row) if row is not None else None

    async def get_role_by_id(self, role_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (await session.execute(select(RoleRow).where(RoleRow.id == role_id))).scalar_one_or_none()
        return _role_to_dict(row) if row is not None else None

    async def create_organization(
        self,
        *,
        name: str,
        website: str | None = None,
        industry: str | None = None,
        company_type: str | None = None,
        country: str | None = None,
        state_region: str | None = None,
        billing_plan: str | None = None,
        account_owner: str | None = None,
        primary_contact: str | None = None,
        feature_package: str | None = None,
        notes: str | None = None,
    ) -> dict:
        row = OrganizationRow(
            name=name,
            website=website,
            industry=industry,
            company_type=company_type,
            country=country,
            state_region=state_region,
            billing_plan=billing_plan,
            account_owner=account_owner,
            primary_contact=primary_contact,
            feature_package=feature_package,
            notes=notes,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return _organization_to_dict(row)

    async def find_organization_by_name(self, name: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(OrganizationRow).where(OrganizationRow.name == name))
            ).scalar_one_or_none()
        return _organization_to_dict(row) if row is not None else None

    async def get_organization(self, organization_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(OrganizationRow).where(OrganizationRow.id == organization_id))
            ).scalar_one_or_none()
        return _organization_to_dict(row) if row is not None else None

    async def list_organizations(self) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (await session.execute(select(OrganizationRow).order_by(OrganizationRow.name))).scalars().all()
            )
        return [_organization_to_dict(r) for r in rows]

    async def create_user(
        self,
        *,
        first_name: str,
        last_name: str,
        email: str,
        organization_id: str,
        role_id: str,
        status: str,
        job_title: str | None = None,
        department: str | None = None,
        phone: str | None = None,
        country: str | None = None,
        state_region: str | None = None,
        primary_use_case: str | None = None,
        market_experience: str | None = None,
        expiration_at: datetime | None = None,
        created_by: str | None = None,
    ) -> dict:
        """Creates a `User` row. This is only ever called from the authenticated
        admin-create-user endpoint (`POST /admin/users`) — there is no other writer,
        by design (see docs/access-model.md "No Self-Registration")."""
        row = UserRow(
            first_name=first_name,
            last_name=last_name,
            email=email.lower(),
            organization_id=organization_id,
            job_title=job_title,
            department=department,
            phone=phone,
            country=country,
            state_region=state_region,
            primary_use_case=primary_use_case,
            market_experience=market_experience,
            role_id=role_id,
            status=status,
            expiration_at=_naive_utc(expiration_at),
            created_by=created_by,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return _user_to_dict(row)

    async def get_user_by_email(self, email: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(select(UserRow).where(UserRow.email == email.lower()))
            ).scalar_one_or_none()
        return _user_to_dict(row) if row is not None else None

    async def get_user_by_id(self, user_id: str) -> dict | None:
        async with self.session_factory() as session:
            row = (await session.execute(select(UserRow).where(UserRow.id == user_id))).scalar_one_or_none()
        return _user_to_dict(row) if row is not None else None

    async def list_users(self) -> list[dict]:
        async with self.session_factory() as session:
            rows = (await session.execute(select(UserRow).order_by(UserRow.created_at.desc()))).scalars().all()
        return [_user_to_dict(r) for r in rows]

    async def update_user_status(self, user_id: str, status: str) -> dict | None:
        async with self.session_factory() as session:
            row = (await session.execute(select(UserRow).where(UserRow.id == user_id))).scalar_one_or_none()
            if row is None:
                return None
            row.status = status
            row.updated_at = datetime.utcnow()
            await session.commit()
            await session.refresh(row)
        return _user_to_dict(row)

    # -- writes ---------------------------------------------------------------------

    async def save_trade_idea(self, trade: TradeIdea, forecast: PriceForecast | None) -> None:
        row = TradeIdeaRow(
            trade_id=str(trade.trade_id),
            strategy=trade.strategy,
            instrument=trade.instrument,
            instrument_type=trade.instrument_type.value,
            direction=trade.direction.value,
            entry=trade.entry,
            target=trade.target,
            stop_or_invalidation=trade.stop_or_invalidation,
            time_horizon=trade.time_horizon,
            expected_return=trade.expected_return,
            expected_loss=trade.expected_loss,
            probability_success=trade.probability_success,
            confidence=trade.confidence,
            thesis=trade.thesis,
            catalysts=trade.catalysts,
            risks=trade.risks,
            invalidation_conditions=trade.invalidation_conditions,
            supporting_data=trade.supporting_data,
            source_citations=trade.source_citations,
            created_at=_naive_utc(trade.created_at),
            expires_at=_naive_utc(trade.expires_at),
            forecast=forecast.model_dump(mode="json") if forecast is not None else None,
        )
        async with self.session_factory() as session:
            await session.merge(row)
            await session.commit()

    async def save_committee_decision(self, trade_id: UUID, decision: InvestmentCommitteeDecision) -> None:
        row = CommitteeDecisionRow(
            original_trade_id=str(trade_id),
            original_trade=decision.original_trade.model_dump(mode="json"),
            bull_case=decision.bull_case,
            bear_case=decision.bear_case,
            skeptic_case=decision.skeptic_case,
            data_quality_assessment=decision.data_quality_assessment,
            portfolio_effect=decision.portfolio_effect,
            consensus_score=decision.consensus_score,
            unresolved_questions=decision.unresolved_questions,
            recommended_action=decision.recommended_action.value,
            decided_at=_naive_utc(decision.decided_at),
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    async def save_risk_check(self, trade_id: UUID, risk_check: RiskCheckResult) -> None:
        row = RiskCheckRow(
            check_id=str(risk_check.check_id),
            trade_id=str(trade_id),
            verdict=risk_check.verdict.value,
            rule_results=[r.model_dump(mode="json") for r in risk_check.rule_results],
            governor_version=risk_check.governor_version,
            evaluated_at=_naive_utc(risk_check.evaluated_at),
        )
        async with self.session_factory() as session:
            await session.merge(row)
            await session.commit()

    async def save_approval(
        self,
        *,
        approval_id: UUID,
        trade_id: UUID,
        state: str,
        actions: list[dict],
        updated_at: datetime,
    ) -> None:
        row = ApprovalRow(
            id=str(approval_id),
            trade_id=str(trade_id),
            state=state,
            actions=actions,
            updated_at=_naive_utc(updated_at),
        )
        async with self.session_factory() as session:
            await session.merge(row)
            await session.commit()

    async def append_decision_journal_entry(self, trade_id: UUID, entry: dict) -> None:
        row = DecisionJournalRow(trade_id=str(trade_id), entry=entry)
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    async def save_post_trade_analysis(self, analysis: PostTradeAnalysis) -> None:
        row = PostTradeAnalysisRow(
            id=str(analysis.id),
            trade_id=str(analysis.trade_id),
            expected_outcome=analysis.expected_outcome,
            actual_outcome=analysis.actual_outcome,
            forecast_error=analysis.forecast_error,
            thesis_accuracy=analysis.thesis_accuracy,
            timing_accuracy=analysis.timing_accuracy,
            risk_accuracy=analysis.risk_accuracy,
            model_contribution=analysis.model_contribution,
            unexpected_events=analysis.unexpected_events,
            lessons=analysis.lessons,
            quadrant=analysis.quadrant.value,
            quant_model_type=analysis.quant_model_type.value if analysis.quant_model_type else None,
            quant_model_version=analysis.quant_model_version,
            quant_predicted_return=analysis.quant_predicted_return,
            quant_forecast_error=analysis.quant_forecast_error,
            quant_up_probability=analysis.quant_up_probability,
            created_at=_naive_utc(analysis.created_at),
        )
        async with self.session_factory() as session:
            await session.merge(row)
            await session.commit()

    async def save_contact_inquiry(
        self,
        *,
        first_name: str,
        last_name: str,
        business_email: str,
        company_name: str,
        job_title: str | None,
        phone: str | None,
        inquiry_type: str,
        message: str,
    ) -> str:
        """Persists a /contact submission. Deliberately takes only plain business-
        inquiry fields — there is no path from here to a `User`/`Organization`/
        `MagicLinkToken` row; this table exists purely for admin visibility into
        inbound inquiries."""
        row = ContactInquiryRow(
            first_name=first_name,
            last_name=last_name,
            business_email=business_email,
            company_name=company_name,
            job_title=job_title,
            phone=phone,
            inquiry_type=inquiry_type,
            message=message,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()
        return row.id

    async def list_contact_inquiries(self) -> list[dict]:
        async with self.session_factory() as session:
            rows = (
                (await session.execute(select(ContactInquiryRow).order_by(ContactInquiryRow.created_at.desc())))
                .scalars()
                .all()
            )
        return [
            {
                "id": r.id,
                "first_name": r.first_name,
                "last_name": r.last_name,
                "business_email": r.business_email,
                "company_name": r.company_name,
                "job_title": r.job_title,
                "phone": r.phone,
                "inquiry_type": r.inquiry_type,
                "message": r.message,
                "created_at": r.created_at,
            }
            for r in rows
        ]

    async def save_risk_limits(self, limits: RiskLimits) -> None:
        row = RiskLimitsRow(
            max_position_size=limits.max_position_size,
            max_risk_per_trade=limits.max_risk_per_trade,
            max_daily_loss=limits.max_daily_loss,
            max_drawdown=limits.max_drawdown,
            max_portfolio_var=limits.max_portfolio_var,
            max_sector_exposure=limits.max_sector_exposure,
            max_contract_exposure=limits.max_contract_exposure,
            max_correlated_exposure=limits.max_correlated_exposure,
            effective_from=_naive_utc(limits.effective_from),
            effective_to=_naive_utc(limits.effective_to),
            set_by_user_id=limits.set_by_user_id,
        )
        async with self.session_factory() as session:
            session.add(row)
            await session.commit()

    # -- hydration --------------------------------------------------------------------

    async def hydrate(self) -> dict:
        """Reloads every persisted object, keyed by trade_id/approval_id (as `str`,
        matching how they're stored) so `AppState` can key its in-memory dicts by
        `UUID(...)` of each key. Returns an empty-but-well-shaped dict when the DB has
        nothing yet (first boot) — safe for `AppState` to iterate unconditionally.
        """
        async with self.session_factory() as session:
            trade_rows = (await session.execute(select(TradeIdeaRow))).scalars().all()
            decision_rows = (await session.execute(select(CommitteeDecisionRow))).scalars().all()
            risk_check_rows = (await session.execute(select(RiskCheckRow))).scalars().all()
            approval_rows = (await session.execute(select(ApprovalRow))).scalars().all()
            journal_rows = (
                (await session.execute(select(DecisionJournalRow).order_by(DecisionJournalRow.created_at)))
                .scalars()
                .all()
            )
            post_trade_rows = (await session.execute(select(PostTradeAnalysisRow))).scalars().all()
            limits_rows = (
                (await session.execute(select(RiskLimitsRow).order_by(RiskLimitsRow.effective_from.desc())))
                .scalars()
                .all()
            )

        trade_ideas: dict[str, TradeIdea] = {}
        forecasts: dict[str, PriceForecast] = {}
        for row in trade_rows:
            trade_ideas[row.trade_id] = TradeIdea(
                trade_id=UUID(row.trade_id),
                strategy=row.strategy,
                instrument=row.instrument,
                instrument_type=row.instrument_type,
                direction=row.direction,
                entry=row.entry,
                target=row.target,
                stop_or_invalidation=row.stop_or_invalidation,
                time_horizon=row.time_horizon,
                expected_return=row.expected_return,
                expected_loss=row.expected_loss,
                probability_success=row.probability_success,
                confidence=row.confidence,
                thesis=row.thesis,
                catalysts=row.catalysts,
                risks=row.risks,
                invalidation_conditions=row.invalidation_conditions,
                supporting_data=row.supporting_data,
                source_citations=row.source_citations,
                created_at=row.created_at,
                expires_at=row.expires_at,
            )
            if row.forecast is not None:
                forecasts[row.trade_id] = PriceForecast.model_validate(row.forecast)

        committee_decisions: dict[str, InvestmentCommitteeDecision] = {}
        for row in decision_rows:
            committee_decisions[row.original_trade_id] = InvestmentCommitteeDecision(
                original_trade=TradeIdea.model_validate(row.original_trade),
                bull_case=row.bull_case,
                bear_case=row.bear_case,
                skeptic_case=row.skeptic_case,
                data_quality_assessment=row.data_quality_assessment,
                portfolio_effect=row.portfolio_effect,
                consensus_score=row.consensus_score,
                unresolved_questions=row.unresolved_questions,
                recommended_action=row.recommended_action,
                decided_at=row.decided_at,
            )

        risk_checks: dict[str, RiskCheckResult] = {}
        for row in risk_check_rows:
            risk_checks[row.trade_id] = RiskCheckResult(
                check_id=UUID(row.check_id),
                trade_id=UUID(row.trade_id),
                verdict=row.verdict,
                rule_results=row.rule_results,
                governor_version=row.governor_version,
                evaluated_at=row.evaluated_at,
            )

        approvals: list[dict] = [
            {
                "id": row.id,
                "trade_id": row.trade_id,
                "state": row.state,
                "actions": row.actions,
                "updated_at": row.updated_at,
            }
            for row in approval_rows
        ]

        decision_journal: dict[str, list[dict]] = {}
        for row in journal_rows:
            decision_journal.setdefault(row.trade_id, []).append(row.entry)

        post_trade_analyses: dict[str, PostTradeAnalysis] = {}
        for row in post_trade_rows:
            post_trade_analyses[row.trade_id] = PostTradeAnalysis(
                id=UUID(row.id),
                trade_id=UUID(row.trade_id),
                expected_outcome=row.expected_outcome,
                actual_outcome=row.actual_outcome,
                forecast_error=row.forecast_error,
                thesis_accuracy=row.thesis_accuracy,
                timing_accuracy=row.timing_accuracy,
                risk_accuracy=row.risk_accuracy,
                model_contribution=row.model_contribution,
                unexpected_events=row.unexpected_events,
                lessons=row.lessons,
                quadrant=row.quadrant,
                quant_model_type=row.quant_model_type,
                quant_model_version=row.quant_model_version,
                quant_predicted_return=row.quant_predicted_return,
                quant_forecast_error=row.quant_forecast_error,
                quant_up_probability=row.quant_up_probability,
                created_at=row.created_at,
            )

        risk_limits: RiskLimits | None = None
        if limits_rows:
            latest = limits_rows[0]
            risk_limits = RiskLimits(
                max_position_size=latest.max_position_size,
                max_risk_per_trade=latest.max_risk_per_trade,
                max_daily_loss=latest.max_daily_loss,
                max_drawdown=latest.max_drawdown,
                max_portfolio_var=latest.max_portfolio_var,
                max_sector_exposure=latest.max_sector_exposure,
                max_contract_exposure=latest.max_contract_exposure,
                max_correlated_exposure=latest.max_correlated_exposure,
                effective_from=latest.effective_from,
                effective_to=latest.effective_to,
                set_by_user_id=latest.set_by_user_id,
            )

        return {
            "trade_ideas": trade_ideas,
            "forecasts": forecasts,
            "committee_decisions": committee_decisions,
            "risk_checks": risk_checks,
            "approvals": approvals,
            "decision_journal": decision_journal,
            "post_trade_analyses": post_trade_analyses,
            "risk_limits": risk_limits,
        }
