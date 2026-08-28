"""Enterprise Opportunity Engine (docs/alpha-intelligence.md section 11.7,
Milestone 10): human-reviewed, never-auto-executed opportunity candidates drafted
by cross-referencing an organization's own proprietary position data against the
Alpha Intelligence Layer's signals/consensus. Every endpoint here is scoped to
the caller's own resolved organization -- there is no platform-wide opportunity
feed, since an opportunity is inherently derived from one organization's own
data (see `EnterpriseOpportunity`'s docstring)."""

from __future__ import annotations

from enterprise_data_service import build_overlay
from fastapi import APIRouter, Depends, HTTPException
from fundamentals_service.pipeline_graph import to_geojson_like
from pydantic import BaseModel
from schemas import EnterpriseOpportunityStatus

from ..auth import User
from ..deps import AppStateDep
from ..entitlements import (
    filter_entitled_enterprise_datasets,
    record_is_visible,
    require_permission,
    resolve_organization_id,
    resolve_organization_scope,
)

router = APIRouter(prefix="/alpha/enterprise", tags=["alpha"])

_RequireOpportunitiesView = Depends(require_permission("enterprise_opportunities.view"))
_RequireOpportunitiesGenerate = Depends(require_permission("enterprise_opportunities.generate"))
_RequireOpportunitiesReview = Depends(require_permission("enterprise_opportunities.review"))
_RequireEnterpriseDataQuery = Depends(require_permission("enterprise_data.query"))


@router.post("/opportunities/generate")
async def generate_opportunities(state: AppStateDep, user: User = _RequireOpportunitiesGenerate) -> list[dict]:
    """Runs `EnterpriseOpportunityEngine` for the caller's own organization and
    persists every candidate as a `PENDING` opportunity. 400 if the caller's
    organization can't be resolved -- generation is inherently org-scoped, so
    there is nothing to run it against otherwise."""
    organization_id, _unrestricted = await resolve_organization_scope(user, state)
    if organization_id is None:
        raise HTTPException(status_code=400, detail="Cannot resolve caller's organization")
    created = await state.generate_enterprise_opportunities(organization_id=organization_id)
    return [o.model_dump(mode="json") for o in created]


@router.get("/opportunities")
async def list_opportunities(
    state: AppStateDep,
    user: User = _RequireOpportunitiesView,
    status: EnterpriseOpportunityStatus | None = None,
    limit: int = 50,
) -> list[dict]:
    """Most-recent-first, scoped to the caller's own organization. A caller
    whose organization can't be resolved sees an empty list, not an error --
    there is no platform-wide fallback to show them instead."""
    organization_id, _unrestricted = await resolve_organization_scope(user, state)
    if organization_id is None:
        return []
    return await state.repo.list_enterprise_opportunities(
        organization_id=organization_id, status=status.value if status is not None else None, limit=limit
    )


@router.get("/opportunities/{opportunity_id}")
async def get_opportunity(
    opportunity_id: str, state: AppStateDep, user: User = _RequireOpportunitiesView
) -> dict:
    opportunity = await state.repo.get_enterprise_opportunity(opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    organization_id, unrestricted = await resolve_organization_scope(user, state)
    if not record_is_visible(opportunity["organization_id"], organization_id, unrestricted):
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return opportunity


class _OpportunityReviewRequest(BaseModel):
    status: EnterpriseOpportunityStatus


@router.post("/opportunities/{opportunity_id}/review")
async def review_opportunity(
    opportunity_id: str,
    body: _OpportunityReviewRequest,
    state: AppStateDep,
    user: User = _RequireOpportunitiesReview,
) -> dict:
    """Approves or rejects a candidate opportunity -- always human-reviewed, and
    this never triggers any trade or position change on its own (see
    `EnterpriseOpportunity`'s docstring: "nothing here is ever auto-executed")."""
    if body.status == EnterpriseOpportunityStatus.PENDING:
        raise HTTPException(status_code=400, detail="Cannot review an opportunity back to PENDING")
    opportunity = await state.repo.get_enterprise_opportunity(opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    organization_id, unrestricted = await resolve_organization_scope(user, state)
    if not record_is_visible(opportunity["organization_id"], organization_id, unrestricted):
        raise HTTPException(status_code=404, detail="Opportunity not found")
    updated = await state.review_enterprise_opportunity(opportunity_id, status=body.status.value, reviewed_by=user.user_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    return updated


@router.get("/pipeline-overlay")
async def pipeline_overlay(state: AppStateDep, user: User = _RequireEnterpriseDataQuery) -> dict:
    """Enterprise Digital Twin overlay (docs/alpha-intelligence.md section 11.7,
    Milestone 10): the same public pipeline digital twin `GET
    /fundamentals/pipeline/graph` returns, plus an `overlay.assets` layer of the
    caller's own organization's `ASSET`/`FACILITY`-domain enterprise records
    that name a real node in the graph -- tenant-isolated (only the caller's own
    resolved organization's datasets, and further narrowed to only datasets `user`
    is fine-grained-entitled to see via `filter_entitled_enterprise_datasets`),
    never merged into the public graph itself. Returns `overlay.assets=[]` (not an
    error) when the caller's organization can't be resolved or has registered no
    matching (entitled) data."""
    if state.pipeline_graph is None:
        raise HTTPException(status_code=503, detail="Pipeline graph not yet seeded")
    graph = to_geojson_like(state.pipeline_graph)
    known_node_ids = {n["id"] for n in graph["nodes"]}

    organization_id = await resolve_organization_id(user, state)
    overlay_points: list[dict] = []
    if organization_id is not None:
        datasets = await state.repo.list_enterprise_datasets(organization_id=organization_id)
        datasets = await filter_entitled_enterprise_datasets(user, state, datasets)
        overlay_datasets = [d for d in datasets if d["domain"] in ("ASSET", "FACILITY")]
        records_by_dataset = {
            d["id"]: await state.repo.list_enterprise_records(d["id"], limit=200) for d in overlay_datasets
        }
        points = build_overlay(records_by_dataset=records_by_dataset, known_node_ids=known_node_ids)
        overlay_points = [
            {
                "dataset_id": p.dataset_id,
                "record_id": p.record_id,
                "pipeline_node_id": p.pipeline_node_id,
                "label": p.label,
            }
            for p in points
        ]

    return {**graph, "classification": "SIMULATED", "overlay": {"assets": overlay_points}}
