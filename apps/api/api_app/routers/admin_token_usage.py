"""Super-admin Token Usage — LLM token counts + cost, aggregated for the
Command Center. Gated by the SUPER_ADMIN-only `admin.system_settings` permission."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..auth import User
from ..entitlements import require_permission
from ..state import get_app_state

router = APIRouter(prefix="/admin/token-usage", tags=["admin-token-usage"])

_RequireSystemSettings = Depends(require_permission("admin.system_settings"))


@router.get("/summary")
async def token_usage_summary(_admin: User = _RequireSystemSettings) -> dict:
    state = await get_app_state()
    return await state.repo.llm_usage_summary()
