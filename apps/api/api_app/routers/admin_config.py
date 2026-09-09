"""Super-admin Configuration API — GUI management of the app's environment
settings (docs/DEPLOY-MAC-MINI.md follow-on). Gated by the SUPER_ADMIN-only
`admin.system_settings` permission. Values persist (secrets encrypted) via
`config_store`; `reload` re-applies them + rebuilds the data-provider registry
without a container restart (settings marked `restart_required` still need one).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import User
from ..deps import AppStateDep
from ..entitlements import require_permission
from .. import config_store

router = APIRouter(prefix="/admin/config", tags=["admin-config"])

_RequireSystemSettings = Depends(require_permission("admin.system_settings"))


class SetRequest(BaseModel):
    value: str


class TestRequest(BaseModel):
    value: str


@router.get("")
async def list_config(state: AppStateDep, _admin: User = _RequireSystemSettings) -> dict:
    items = await config_store.masked_view(state.repo.session_factory)
    # Preserve catalog order but group for the UI.
    groups: list[str] = []
    for it in items:
        if it["group"] not in groups:
            groups.append(it["group"])
    return {"groups": groups, "items": items}


@router.put("/{key}")
async def set_config(key: str, body: SetRequest, state: AppStateDep, _admin: User = _RequireSystemSettings) -> dict:
    if key not in config_store.CATALOG_BY_KEY:
        return {"ok": False, "error": "Unknown setting."}
    if body.value == "":
        await config_store.delete_value(state.repo.session_factory, key)
    else:
        await config_store.set_value(state.repo.session_factory, key, body.value)
    return {"ok": True}


@router.post("/{key}/test")
async def test_config(key: str, body: TestRequest, _admin: User = _RequireSystemSettings) -> dict:
    ok, message = await config_store.test_value(key, body.value)
    return {"ok": ok, "message": message}


@router.post("/reload")
async def reload_config(state: AppStateDep, _admin: User = _RequireSystemSettings) -> dict:
    result = await config_store.reload_runtime(state)
    return {"ok": True, **result}
