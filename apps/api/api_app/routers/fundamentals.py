from __future__ import annotations

from datetime import date

from fastapi import APIRouter
from fundamentals_service.lng import compute_netback
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
async def pipeline_graph():
    """Minimal illustrative digital-twin graph (see docs/database-schema.md §pipeline
    nodes/edges). A handful of representative nodes; the full US network model is
    Milestone 10 scope."""
    nodes = [
        {"id": "permian", "type": "production_basin", "name": "Permian Basin", "lat": 31.9, "lon": -102.6},
        {"id": "waha", "type": "hub", "name": "Waha Hub", "lat": 31.05, "lon": -103.13},
        {"id": "henry_hub", "type": "hub", "name": "Henry Hub", "lat": 29.9, "lon": -91.8},
        {"id": "sabine_pass", "type": "LNG_terminal", "name": "Sabine Pass LNG", "lat": 29.7, "lon": -93.87},
        {"id": "freeport", "type": "LNG_terminal", "name": "Freeport LNG", "lat": 28.95, "lon": -95.35},
        {"id": "aliso_canyon", "type": "storage_facility", "name": "Aliso Canyon", "lat": 34.32, "lon": -118.56},
    ]
    edges = [
        {"id": "permian_waha", "type": "pipeline", "from": "permian", "to": "waha", "capacity_bcf_d": 2.5, "utilization": 0.82},
        {"id": "waha_henry", "type": "pipeline", "from": "waha", "to": "henry_hub", "capacity_bcf_d": 4.0, "utilization": 0.65},
        {"id": "henry_sabine", "type": "pipeline", "from": "henry_hub", "to": "sabine_pass", "capacity_bcf_d": 5.0, "utilization": 0.9},
        {"id": "henry_freeport", "type": "pipeline", "from": "henry_hub", "to": "freeport", "capacity_bcf_d": 2.4, "utilization": 0.58},
    ]
    return {"nodes": nodes, "edges": edges, "classification": "SIMULATED"}
