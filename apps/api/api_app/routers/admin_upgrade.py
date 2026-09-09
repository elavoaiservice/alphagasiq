"""Super-admin Upgrade API — trigger a host-side deploy from the admin portal
(docs/DEPLOY-MAC-MINI.md). The API never touches Docker or git directly: it just
writes a trigger file into a shared volume (`/deploy`, bind-mounted from the
host's ~/agiq-deploy). A host launchd watcher runs the actual
git-pull + rebuild + restart and streams progress to `status.log`, which this
router tails back to the UI. Gated by the SUPER_ADMIN-only
`admin.system_settings` permission.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from ..auth import User
from ..entitlements import require_permission

router = APIRouter(prefix="/admin/upgrade", tags=["admin-upgrade"])

_RequireSystemSettings = Depends(require_permission("admin.system_settings"))

_DEPLOY_DIR = "/deploy"
_TRIGGER = os.path.join(_DEPLOY_DIR, "trigger")
_LOCK = os.path.join(_DEPLOY_DIR, "upgrade.lock")
_LOG = os.path.join(_DEPLOY_DIR, "status.log")


@router.post("")
async def trigger_upgrade(_admin: User = _RequireSystemSettings) -> dict:
    if not os.path.isdir(_DEPLOY_DIR):
        return {"ok": False, "error": "Upgrade agent not configured (the /deploy volume is not mounted)."}
    if os.path.exists(_LOCK):
        return {"ok": False, "error": "An upgrade is already running."}
    try:
        with open(_TRIGGER, "w") as f:
            f.write(datetime.now(timezone.utc).isoformat())
        return {"ok": True}
    except OSError as e:
        return {"ok": False, "error": f"Could not signal the upgrade agent: {e}"}


@router.get("/status")
async def upgrade_status(_admin: User = _RequireSystemSettings) -> dict:
    configured = os.path.isdir(_DEPLOY_DIR)
    running = os.path.exists(_LOCK)
    log = ""
    if configured and os.path.exists(_LOG):
        try:
            with open(_LOG) as f:
                log = f.read()[-12000:]
        except OSError:
            log = ""
    return {"configured": configured, "running": running, "log": log}
