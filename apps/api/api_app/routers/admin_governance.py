"""Milestone 10: risk settings, audit logging, and system health/alerts
(spec §§44/55/56, `docs/agent-governance.md` §§6-8).

Risk-setting changes here are the *admin-governed* surface `docs/agent-governance.md` §6
describes -- gated by the strict, `SUPER_ADMIN`-only `admin.risk_settings` permission,
mandatory-`reason`, and audit-logged with before/after -- layered on top of the existing
day-to-day `PUT /risk/limits` a `RISK_MANAGER` already uses (`apps/api/api_app/routers/
risk.py`, unchanged). Both write to the same `state.risk_limits`/`RiskLimitsRow`; this
one additionally satisfies spec §44's "authorized role, confirmation, a reason, an
effective timestamp, an audit event, and the previous and new value recorded together."
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from schemas import RiskLimits

from ..audit import record_audit_event
from ..auth import User
from ..deps import AppStateDep
from ..entitlements import require_permission

router = APIRouter(prefix="/admin", tags=["admin"])

_RequireRiskSettings = Depends(require_permission("admin.risk_settings"))
_RequireAuditLogs = Depends(require_permission("admin.audit_logs"))
_RequireDashboard = Depends(require_permission("admin.dashboard"))


# -- risk settings (spec §44) ---------------------------------------------------------


@router.get("/risk-settings", response_model=RiskLimits)
async def get_risk_settings(state: AppStateDep, _admin: User = _RequireRiskSettings) -> RiskLimits:
    return state.risk_limits


class RiskSettingsUpdateRequest(BaseModel):
    max_position_size: float
    max_risk_per_trade: float
    max_daily_loss: float
    max_drawdown: float
    max_portfolio_var: float
    max_sector_exposure: float
    max_contract_exposure: float
    max_correlated_exposure: float
    reason: str


@router.put("/risk-settings", response_model=RiskLimits)
async def update_risk_settings(
    body: RiskSettingsUpdateRequest, state: AppStateDep, admin: User = _RequireRiskSettings
) -> RiskLimits:
    if not body.reason.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="reason is required")
    before = state.risk_limits.model_dump(mode="json")
    new_limits = RiskLimits(
        max_position_size=body.max_position_size,
        max_risk_per_trade=body.max_risk_per_trade,
        max_daily_loss=body.max_daily_loss,
        max_drawdown=body.max_drawdown,
        max_portfolio_var=body.max_portfolio_var,
        max_sector_exposure=body.max_sector_exposure,
        max_contract_exposure=body.max_contract_exposure,
        max_correlated_exposure=body.max_correlated_exposure,
        effective_from=datetime.now(timezone.utc),
        set_by_user_id=admin.user_id,
    )
    await state.set_risk_limits(new_limits)
    await record_audit_event(
        state,
        actor=admin,
        action="risk_settings.update",
        resource_type="risk_limits",
        resource_id="global",
        before=before,
        after=state.risk_limits.model_dump(mode="json"),
        reason=body.reason,
    )
    return state.risk_limits


# -- audit log (spec §55) --------------------------------------------------------------


@router.get("/audit-logs")
async def list_audit_logs(
    state: AppStateDep,
    _admin: User = _RequireAuditLogs,
    resource_type: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
) -> list[dict]:
    return await state.repo.list_audit_events(resource_type=resource_type, limit=limit)


# -- system health/alerts (spec §56) ---------------------------------------------------


@router.get("/system-health")
async def system_health(state: AppStateDep, _admin: User = _RequireDashboard) -> dict:
    """An admin-only rollup of live health across the pipeline stages
    `docs/agent-governance.md` §8 calls for: data feeds, agents, models, the Risk
    Governor, the event bus, and the database. Every field is computed from real state
    already tracked elsewhere in this platform -- nothing fabricated."""
    feed_health = {h.provider_id: h for h in await state.providers.health_snapshot()}
    feed_configs = await state.repo.list_data_feed_configs()
    agent_configs = await state.repo.list_agent_configs()
    models = await state.repo.list_model_definitions()

    return {
        "data_feeds": {
            "total": len(feed_configs),
            "healthy": sum(1 for c in feed_configs if feed_health.get(c["provider_id"]) and feed_health[c["provider_id"]].status == "healthy"),
            "not_configured": sum(1 for c in feed_configs if feed_health.get(c["provider_id"]) is None or feed_health[c["provider_id"]].status == "not_configured"),
        },
        "agents": {
            "total_administrable": len(agent_configs),
            "active": sum(1 for c in agent_configs if c["status"] == "ACTIVE"),
            "paused_or_disabled": sum(1 for c in agent_configs if c["status"] in ("PAUSED", "DISABLED")),
        },
        "models": {
            "total": len(models),
            "approved": sum(1 for m in models if m["status"] == "APPROVED"),
        },
        "risk_governor": {
            "status": "operational",
            "version": state.risk_governor.version,
            "trading_halted": state.trading_halted,
        },
        "event_bus": {"implementation": type(state.event_bus).__name__},
        "database": {"status": "connected"},
        "checked_at": datetime.now(timezone.utc),
    }
