"""Milestone 6: the rest of the admin console beyond user/organization provisioning
(`admin_users.py`) -- overview metrics (spec §31), feature management (spec §34), and
system configuration (spec §38). Every endpoint is gated by the real permission the
access-model spec assigns it, per `entitlements.py`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from ..account_states import AccountStatus
from ..auth import User
from ..deps import AppStateDep
from ..entitlements import require_permission

router = APIRouter(prefix="/admin", tags=["admin"])

_RequireDashboard = Depends(require_permission("admin.dashboard"))
_RequireFeatureManagement = Depends(require_permission("admin.feature_management"))
_RequireUsersFeatures = Depends(require_permission("admin.users.features"))
_RequireSystemSettings = Depends(require_permission("admin.system_settings"))


@router.get("/overview")
async def admin_overview(state: AppStateDep, _admin: User = _RequireDashboard) -> dict:
    """Spec §31 "Admin Overview". Fields that depend on subsystems not yet built
    (model health -> Milestone 9/10; risk alerts and failed-authentication tracking ->
    Milestone 10's audit log) are reported as `None` with an explanatory
    `not_yet_available` list, rather than fabricated — this platform's consistent
    honest-stub convention."""
    users = await state.repo.list_users()
    organizations = await state.repo.list_organizations()
    today = datetime.now(timezone.utc).date()

    health_by_provider = {h.provider_id: h for h in await state.providers.health_snapshot()}
    feed_configs = await state.repo.list_data_feed_configs()

    def _logged_in_today(user: dict) -> bool:
        last_login = user["last_login_at"]
        if last_login is None:
            return False
        if last_login.tzinfo is None:
            last_login = last_login.replace(tzinfo=timezone.utc)
        return last_login.date() == today

    chief_trading_agent_queries = 0
    for conversation in await state.repo.list_chat_conversations():
        messages = await state.repo.list_chat_messages(conversation["id"])
        chief_trading_agent_queries += sum(1 for m in messages if m["role"] == "assistant")

    return {
        "active_users": sum(1 for u in users if u["status"] == AccountStatus.ACTIVE.value),
        "invited_users": sum(1 for u in users if u["status"] == AccountStatus.INVITED.value),
        "suspended_users": sum(1 for u in users if u["status"] == AccountStatus.SUSPENDED.value),
        "active_organizations": sum(1 for o in organizations if o["status"] == "ACTIVE"),
        "users_logged_in_today": sum(1 for u in users if _logged_in_today(u)),
        "chief_trading_agent_queries": chief_trading_agent_queries,
        "paper_trading_activity": {
            "open_positions": len(
                [p for p in state.paper_adapter.portfolio.positions.values() if p.quantity != 0]
            ),
            "total_fills": len(state.paper_adapter.portfolio.fills),
        },
        "agent_execution_health": {
            "total_executions_logged": len(state.agent_execution_log),
        },
        "data_feed_health": {
            "total_feeds": len(feed_configs),
            "healthy": sum(
                1
                for c in feed_configs
                if (health_by_provider.get(c["provider_id"]) is not None
                    and health_by_provider[c["provider_id"]].status == "healthy")
            ),
            "degraded_or_unavailable": sum(
                1
                for c in feed_configs
                if (health_by_provider.get(c["provider_id"]) is not None
                    and health_by_provider[c["provider_id"]].status in ("degraded", "unavailable"))
            ),
            "not_configured": sum(
                1
                for c in feed_configs
                if (health_by_provider.get(c["provider_id"]) is None
                    or health_by_provider[c["provider_id"]].status == "not_configured")
            ),
        },
        "stale_data_feeds": sum(
            1
            for c in feed_configs
            if (
                c["freshness_threshold_seconds"] is not None
                and health_by_provider.get(c["provider_id"]) is not None
                and health_by_provider[c["provider_id"]].freshness_seconds is not None
                and health_by_provider[c["provider_id"]].freshness_seconds > c["freshness_threshold_seconds"]
            )
        ),
        "model_health": None,
        "system_alerts": None,
        "failed_authentication_attempts": None,
        "critical_risk_alerts": None,
        "not_yet_available": [
            "model_health",
            "system_alerts",
            "failed_authentication_attempts",
            "critical_risk_alerts",
        ],
    }


# -- feature management (spec §34) --------------------------------------------------


class FeatureToggleRequest(BaseModel):
    enabled: bool


@router.get("/features")
async def list_features(state: AppStateDep, _admin: User = _RequireFeatureManagement) -> list[dict]:
    return await state.repo.list_features()


@router.put("/features/{feature_key}")
async def set_feature_globally_enabled(
    feature_key: str, body: FeatureToggleRequest, state: AppStateDep, _admin: User = _RequireFeatureManagement
) -> dict:
    try:
        return await state.repo.set_feature_globally_enabled(feature_key, body.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/roles/{role_name}/features")
async def get_role_features(role_name: str, state: AppStateDep, _admin: User = _RequireFeatureManagement) -> dict:
    role = await state.repo.get_role_by_name(role_name)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown role")
    granted = await state.repo.get_role_feature_keys(role["id"])
    features = await state.repo.list_features()
    return {"role": role_name, "features": {f["key"]: (f["key"] in granted) for f in features}}


@router.put("/roles/{role_name}/features/{feature_key}")
async def set_role_feature(
    role_name: str, feature_key: str, body: FeatureToggleRequest, state: AppStateDep, _admin: User = _RequireFeatureManagement
) -> dict:
    role = await state.repo.get_role_by_name(role_name)
    if role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown role")
    try:
        await state.repo.set_role_feature_entitlement(role_id=role["id"], feature_key=feature_key, enabled=body.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    granted = await state.repo.get_role_feature_keys(role["id"])
    return {"role": role_name, "feature": feature_key, "enabled": feature_key in granted}


@router.put("/organizations/{organization_id}/features/{feature_key}")
async def set_organization_feature(
    organization_id: str,
    feature_key: str,
    body: FeatureToggleRequest,
    state: AppStateDep,
    _admin: User = _RequireFeatureManagement,
) -> dict:
    if await state.repo.get_organization(organization_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    try:
        await state.repo.set_organization_feature_override(
            organization_id=organization_id, feature_key=feature_key, enabled=body.enabled
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"organization_id": organization_id, "feature": feature_key, "enabled": body.enabled}


@router.put("/users/{user_id}/features/{feature_key}")
async def set_user_feature(
    user_id: str, feature_key: str, body: FeatureToggleRequest, state: AppStateDep, _admin: User = _RequireUsersFeatures
) -> dict:
    """Spec §32's "Enable/disable Chief Trading Agent / Portfolio Access / Risk
    Analytics / Paper Trading / API Access" — each is one of the `security_sensitive`
    features, so an `enabled=True` override here can never exceed what the user's
    role/organization already allow (see `entitlements.py::get_effective_features`)."""
    if await state.repo.get_user_by_id(user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    try:
        await state.repo.set_user_feature_override(user_id=user_id, feature_key=feature_key, enabled=body.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"user_id": user_id, "feature": feature_key, "enabled": body.enabled}


# -- system configuration (spec §38) -------------------------------------------------


class SystemSettingUpdateRequest(BaseModel):
    value: object


@router.get("/settings")
async def list_settings(state: AppStateDep, _admin: User = _RequireSystemSettings) -> list[dict]:
    return await state.repo.list_system_settings()


@router.get("/settings/{key}")
async def get_setting(key: str, state: AppStateDep, _admin: User = _RequireSystemSettings) -> dict:
    setting = await state.repo.get_system_setting(key)
    if setting is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown setting key")
    return setting


@router.put("/settings/{key}")
async def update_setting(
    key: str, body: SystemSettingUpdateRequest, state: AppStateDep, admin: User = _RequireSystemSettings
) -> dict:
    try:
        return await state.repo.set_system_setting(key, body.value, updated_by=admin.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/settings/{key}/history")
async def get_setting_history(key: str, state: AppStateDep, _admin: User = _RequireSystemSettings) -> list[dict]:
    if await state.repo.get_system_setting(key) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown setting key")
    return await state.repo.list_system_setting_history(key)
