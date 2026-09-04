"""Public ingress for `EnterpriseConnectorType.WEBHOOK` sources
(docs/alpha-intelligence.md section 11.3): an external system POSTs
already-produced rows here; this endpoint HMAC-verifies the request against a
secret the admin env-provisions and names, but never stores, via
`EnterpriseDataSource.connection_config.signing_secret_env_var` -- the same
no-credential posture every other connector in this codebase takes -- and
stages accepted rows durably (`EnterpriseWebhookStagedRowRow`) for an admin to
preview/ingest through the existing `/admin/enterprise-data/datasets/{id}/
ingest` flow (`enterprise_data_service.connector.WebhookConnector` reads from
that same staging buffer). Deliberately unauthenticated by user session -- the
caller is an external system, not a logged-in user -- so the signature check
is the only gate: a source with no `signing_secret_env_var` configured (or
whose secret doesn't resolve) refuses all pushes rather than accepting
unverified data.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os

from fastapi import APIRouter, Header, HTTPException, Request, status
from schemas import EnterpriseConnectorType

from ..deps import AppStateDep

router = APIRouter(prefix="/webhooks/enterprise-data", tags=["webhooks"])

_SIGNATURE_HEADER = "X-AlphaGasIQ-Signature"


@router.post("/{source_id}", status_code=status.HTTP_202_ACCEPTED)
async def receive_webhook(
    source_id: str,
    request: Request,
    state: AppStateDep,
    x_alphagasiq_signature: str | None = Header(default=None, alias=_SIGNATURE_HEADER),
) -> dict:
    source = await state.repo.get_enterprise_data_source(source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")
    if source["connector_type"] != EnterpriseConnectorType.WEBHOOK.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Source is not a WEBHOOK connector")

    secret_env_var = (source.get("connection_config") or {}).get("signing_secret_env_var")
    secret = os.environ.get(secret_env_var) if secret_env_var else None
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source has no signing_secret_env_var configured -- unverified webhook pushes are refused",
        )

    raw_body = await request.body()
    expected_signature = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided_signature = (x_alphagasiq_signature or "").strip().removeprefix("sha256=")
    if not provided_signature or not hmac.compare_digest(expected_signature, provided_signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing signature")

    try:
        payload = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Body must be valid JSON") from exc

    if isinstance(payload, dict):
        candidate_rows = payload.get("rows", [])
    elif isinstance(payload, list):
        candidate_rows = payload
    else:
        candidate_rows = []
    rows = [r for r in candidate_rows if isinstance(r, dict)]

    staged = await state.repo.stage_enterprise_webhook_rows(source_id, rows)
    await state.repo.record_enterprise_data_event(
        source_id=source_id, event_type="webhook_received", status="success", detail=f"{staged} row(s) staged"
    )
    return {"staged": staged}
