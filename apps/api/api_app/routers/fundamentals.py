from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException
from fundamentals_service.lng import compute_netback
from fundamentals_service.pipeline_graph import to_geojson_like
from fundamentals_service.power_burn import estimate_power_burn_bcf_d
from fundamentals_service.storage_forecast import forecast_storage_week, week_ending_for

from ..deps import AppStateDep

router = APIRouter(prefix="/fundamentals", tags=["fundamentals"])


@router.get("/balance/daily")
async def balance_daily(state: AppStateDep, days: int = 30):
    recent = state.balances[-days:]
    return [
        {
            "flow_date": b.flow_date,
            "supply_total_bcf": round(b.supply_total_bcf, 2),
            "demand_total_bcf": round(b.demand_total_bcf, 2),
            "balance_bcf": round(b.balance_bcf, 2),
            "classification": "SIMULATED",
        }
        for b in recent
    ]


@router.get("/storage/current")
async def storage_current(state: AppStateDep):
    return {**state.storage_baseline, "classification": "SIMULATED", "as_of": date.today()}


@router.get("/storage/forecast")
async def storage_forecast(state: AppStateDep):
    today = date.today()
    week_ending = week_ending_for(today)
    week = [b for b in state.balances if b.flow_date <= week_ending][-7:]
    forecast = forecast_storage_week(
        week_ending=week_ending,
        daily_balances=week,
        five_year_average_bcf=state.storage_baseline["five_year_average_bcf"],
        last_year_bcf=state.storage_baseline["year_ago_inventory_bcf"],
        drivers=["Lower-48 balance engine (SIMULATED seed data)"],
    )
    payload = forecast.model_dump(mode="json")
    payload["classification"] = "SIMULATED"
    return payload


@router.get("/lng/terminals")
async def lng_terminals(state: AppStateDep):
    hh_price = state.market_curve[0].value if state.market_curve else 3.0
    ttf_price = state.ttf_price[0].value if state.ttf_price else 9.5
    netback = compute_netback(destination="TTF", henry_hub_price=hh_price, destination_price=ttf_price)
    return {
        "terminals": [
            {
                "name": t.name,
                "location": t.location,
                "capacity_bcf_d": t.capacity_bcf_d,
                "feedgas_bcf_d": t.feedgas_bcf_d,
                "utilization": t.utilization,
                "maintenance_status": t.maintenance_status,
                "outage_status": t.outage_status,
            }
            for t in state.lng_terminals
        ],
        "ttf_netback": netback.__dict__,
        "classification": "SIMULATED",
    }


@router.get("/power-burn")
async def power_burn(state: AppStateDep):
    return {
        "markets": [
            {
                "iso": m.iso,
                "load_gw": m.load_gw,
                "gas_generation_gw": m.gas_generation_gw,
                "estimated_power_burn_bcf_d": estimate_power_burn_bcf_d(m),
            }
            for m in state.power_markets
        ],
        "total_power_burn_bcf_d": round(sum(estimate_power_burn_bcf_d(m) for m in state.power_markets), 2),
        "classification": "SIMULATED",
    }


@router.get("/pipeline/graph")
async def pipeline_graph(state: AppStateDep):
    """Pipeline digital-twin graph (see docs/database-schema.md §pipeline nodes/edges
    and docs/architecture.md Milestone 10): production basins, processing plants,
    hubs, storage, city gates, power plants, LNG terminals, and Mexico export points,
    connected by pipeline/transport-contract/interconnect edges carrying
    capacity/flow/utilization/maintenance/constraint/basis data."""
    if state.pipeline_graph is None:
        raise HTTPException(status_code=503, detail="Pipeline graph not yet seeded")
    return {**to_geojson_like(state.pipeline_graph), "classification": "SIMULATED"}


@router.get("/pipeline/nodes/{node_id}")
async def pipeline_node_detail(node_id: str, state: AppStateDep):
    if state.pipeline_graph is None:
        raise HTTPException(status_code=503, detail="Pipeline graph not yet seeded")
    node = state.pipeline_graph.node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Unknown pipeline node")
    edges = state.pipeline_graph.edges_for(node_id)
    return {
        "node": {"id": node.id, "type": node.node_type, "name": node.name, "lat": node.lat, "lon": node.lon},
        "edges": [
            {
                "id": e.id,
                "type": e.edge_type,
                "from": e.from_node_id,
                "to": e.to_node_id,
                "capacity_bcf_d": e.capacity_bcf_d,
                "actual_flow_bcf_d": e.actual_flow_bcf_d,
                "utilization": e.utilization,
                "maintenance": e.maintenance,
                "constraint": e.constraint,
                "basis_relationship": e.basis_relationship,
                "is_constrained": e.is_constrained,
            }
            for e in edges
        ],
        "classification": "SIMULATED",
    }
