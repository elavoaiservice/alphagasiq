"""Pipeline digital twin: a graph-based model of US natural-gas infrastructure.

Node types: production_basin, processing_plant, pipeline_interconnect,
storage_facility, city_gate, power_plant, LNG_terminal, export_point, hub.

Edge types: pipeline, transport_contract, interconnect.

This is a relational (Postgres) implementation of the graph today — see
`infrastructure/db/migrations/001_init.sql` `pipeline_nodes`/`pipeline_edges` — chosen
deliberately over standing up Neo4j for an MVP-scale graph (~25 nodes). The model is
kept portable: every node/edge is a flat, self-contained record with no SQL-specific
traversal logic, so a future migration to Neo4j (docs/architecture.md §6) only needs a
loader, not a redesign.

`build_default_pipeline_graph()` returns SIMULATED seed data — representative capacity
and flow figures for major basins/hubs/terminals, not real-time operational data (which
would come from FERC/pipeline bulletin-board connectors per docs/data-sources.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

NodeType = Literal[
    "production_basin",
    "processing_plant",
    "pipeline_interconnect",
    "storage_facility",
    "city_gate",
    "power_plant",
    "LNG_terminal",
    "export_point",
    "hub",
]

EdgeType = Literal["pipeline", "transport_contract", "interconnect"]


@dataclass(frozen=True)
class PipelineNode:
    id: str
    node_type: NodeType
    name: str
    lat: float
    lon: float
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PipelineEdge:
    id: str
    edge_type: EdgeType
    from_node_id: str
    to_node_id: str
    capacity_bcf_d: float
    scheduled_flow_bcf_d: float
    actual_flow_bcf_d: float
    direction: str = "forward"
    maintenance: str | None = None
    constraint: str | None = None
    tariff: str | None = None
    basis_relationship: str | None = None

    @property
    def utilization(self) -> float:
        if self.capacity_bcf_d <= 0:
            return 0.0
        return round(self.actual_flow_bcf_d / self.capacity_bcf_d, 4)

    @property
    def is_constrained(self) -> bool:
        return self.utilization >= 0.9 or self.constraint is not None


@dataclass(frozen=True)
class PipelineGraph:
    nodes: list[PipelineNode]
    edges: list[PipelineEdge]

    def node(self, node_id: str) -> PipelineNode | None:
        return next((n for n in self.nodes if n.id == node_id), None)

    def edges_for(self, node_id: str) -> list[PipelineEdge]:
        return [e for e in self.edges if e.from_node_id == node_id or e.to_node_id == node_id]

    def constrained_edges(self) -> list[PipelineEdge]:
        return [e for e in self.edges if e.is_constrained]

    def total_capacity_bcf_d(self) -> float:
        return round(sum(e.capacity_bcf_d for e in self.edges), 2)

    def total_actual_flow_bcf_d(self) -> float:
        return round(sum(e.actual_flow_bcf_d for e in self.edges), 2)

    def average_utilization(self) -> float:
        if not self.edges:
            return 0.0
        return round(sum(e.utilization for e in self.edges) / len(self.edges), 4)


def build_default_pipeline_graph() -> PipelineGraph:
    nodes = [
        # Production basins
        PipelineNode("permian", "production_basin", "Permian Basin", 31.9, -102.6),
        PipelineNode("haynesville", "production_basin", "Haynesville Shale", 32.5, -93.75),
        PipelineNode("marcellus", "production_basin", "Marcellus/Utica", 39.9, -80.2),
        PipelineNode("eagle_ford", "production_basin", "Eagle Ford Shale", 28.7, -98.5),
        PipelineNode("anadarko", "production_basin", "Anadarko / SCOOP-STACK", 35.5, -98.0),
        PipelineNode("rockies", "production_basin", "Rockies (Piceance/DJ)", 40.0, -108.0),
        # Processing plants
        PipelineNode("waha_proc", "processing_plant", "Waha Processing Complex", 31.1, -103.2),
        PipelineNode("marcellus_proc", "processing_plant", "MarkWest Marcellus Complex", 39.7, -80.0),
        # Hubs
        PipelineNode("waha", "hub", "Waha Hub", 31.05, -103.13),
        PipelineNode("henry_hub", "hub", "Henry Hub", 29.9, -91.8),
        PipelineNode("opal", "hub", "Opal Hub", 41.75, -110.0),
        PipelineNode("dominion_south", "hub", "Dominion South Hub", 39.5, -80.3),
        PipelineNode("socal_citygate", "hub", "SoCal Citygate", 34.05, -118.25),
        PipelineNode("chicago_citygate", "hub", "Chicago Citygate", 41.85, -87.65),
        # Pipeline interconnects
        PipelineNode("agua_dulce", "pipeline_interconnect", "Agua Dulce Interconnect", 27.75, -98.23),
        PipelineNode("transco_station_85", "pipeline_interconnect", "Transco Station 85", 33.9, -84.4),
        # Storage facilities
        PipelineNode("aliso_canyon", "storage_facility", "Aliso Canyon Storage", 34.32, -118.56),
        PipelineNode("moss_bluff", "storage_facility", "Moss Bluff Storage Hub", 30.1, -94.4),
        # City gates
        PipelineNode("nyc_citygate", "city_gate", "New York City Gate", 40.7, -74.0),
        PipelineNode("boston_citygate", "city_gate", "Boston City Gate", 42.36, -71.06),
        # Power plants
        PipelineNode("ercot_ccgt_1", "power_plant", "ERCOT CCGT — Houston Ship Channel", 29.75, -95.1),
        PipelineNode("pjm_ccgt_1", "power_plant", "PJM CCGT — Pennsylvania", 40.3, -76.6),
        # LNG terminals
        PipelineNode("sabine_pass", "LNG_terminal", "Sabine Pass LNG", 29.7, -93.87),
        PipelineNode("corpus_christi", "LNG_terminal", "Corpus Christi LNG", 27.87, -97.27),
        PipelineNode("freeport", "LNG_terminal", "Freeport LNG", 28.95, -95.35),
        PipelineNode("cameron", "LNG_terminal", "Cameron LNG", 29.85, -93.35),
        PipelineNode("calcasieu_pass", "LNG_terminal", "Calcasieu Pass LNG", 29.85, -93.35),
        PipelineNode("plaquemines", "LNG_terminal", "Plaquemines LNG", 29.35, -89.45),
        # Export points (Mexico)
        PipelineNode("eagle_pass", "export_point", "Eagle Pass Export Point (Mexico)", 28.7, -100.5),
        PipelineNode("roma", "export_point", "Roma Export Point (Mexico)", 26.4, -99.0),
    ]

    edges = [
        PipelineEdge("permian_waha_proc", "pipeline", "permian", "waha_proc", 6.0, 4.9, 4.7),
        PipelineEdge("waha_proc_waha", "pipeline", "waha_proc", "waha", 5.5, 4.6, 4.5),
        PipelineEdge(
            "waha_henry", "pipeline", "waha", "henry_hub", 4.0, 2.7, 2.6, basis_relationship="Waha-HH spread widens under takeaway constraint"
        ),
        PipelineEdge(
            "waha_agua_dulce", "pipeline", "waha", "agua_dulce", 2.6, 2.5, 2.5,
            constraint="Near full utilization — limited spare capacity to the Mexico corridor",
        ),
        PipelineEdge("agua_dulce_eagle_ford", "pipeline", "eagle_ford", "agua_dulce", 3.0, 2.2, 2.1),
        PipelineEdge("agua_dulce_eagle_pass", "transport_contract", "agua_dulce", "eagle_pass", 1.8, 1.5, 1.5),
        PipelineEdge("agua_dulce_roma", "transport_contract", "agua_dulce", "roma", 1.2, 0.9, 0.9),
        PipelineEdge("henry_sabine", "pipeline", "henry_hub", "sabine_pass", 5.0, 4.6, 4.55),
        PipelineEdge("henry_freeport", "pipeline", "henry_hub", "freeport", 2.4, 1.5, 1.4, maintenance="Partial feedgas curtailment — compressor maintenance"),
        PipelineEdge("henry_cameron", "pipeline", "henry_hub", "cameron", 2.2, 1.9, 1.85),
        PipelineEdge("henry_plaquemines", "pipeline", "henry_hub", "plaquemines", 1.9, 1.15, 1.1),
        PipelineEdge("henry_calcasieu", "pipeline", "henry_hub", "calcasieu_pass", 1.5, 1.35, 1.3),
        PipelineEdge("henry_moss_bluff", "interconnect", "henry_hub", "moss_bluff", 1.0, 0.4, 0.35),
        PipelineEdge("eagle_ford_agua_dulce_alt", "pipeline", "eagle_ford", "henry_hub", 3.5, 2.0, 1.95),
        PipelineEdge("haynesville_henry", "pipeline", "haynesville", "henry_hub", 6.0, 4.8, 4.7),
        PipelineEdge("anadarko_henry", "pipeline", "anadarko", "henry_hub", 3.0, 2.1, 2.0),
        PipelineEdge("marcellus_proc_link", "pipeline", "marcellus", "marcellus_proc", 8.0, 6.5, 6.3),
        PipelineEdge("marcellus_dominion", "pipeline", "marcellus_proc", "dominion_south", 5.0, 4.2, 4.1),
        PipelineEdge(
            "dominion_transco85", "pipeline", "dominion_south", "transco_station_85", 3.5, 3.4, 3.4,
            constraint="Highly utilized southbound corridor supporting Southeast power burn",
        ),
        PipelineEdge("marcellus_nyc", "pipeline", "marcellus_proc", "nyc_citygate", 2.5, 2.3, 2.35),
        PipelineEdge("marcellus_boston", "pipeline", "marcellus_proc", "boston_citygate", 1.2, 1.1, 1.15,
                     constraint="Winter capacity constraint into New England"),
        PipelineEdge("dominion_chicago", "pipeline", "dominion_south", "chicago_citygate", 2.0, 1.4, 1.35),
        PipelineEdge("rockies_opal", "pipeline", "rockies", "opal", 4.0, 2.6, 2.5),
        PipelineEdge("opal_socal", "pipeline", "opal", "socal_citygate", 2.8, 2.0, 1.95),
        PipelineEdge("socal_aliso", "interconnect", "socal_citygate", "aliso_canyon", 1.5, 0.6, 0.55),
        PipelineEdge("henry_ercot_ccgt1", "pipeline", "henry_hub", "ercot_ccgt_1", 1.0, 0.75, 0.8),
        PipelineEdge("dominion_pjm_ccgt1", "pipeline", "dominion_south", "pjm_ccgt_1", 1.2, 0.95, 1.0),
    ]

    return PipelineGraph(nodes=nodes, edges=edges)


def to_geojson_like(graph: PipelineGraph) -> dict:
    """Serialization shape used by the API (and consumed directly by the frontend's
    lightweight SVG map — see docs/frontend-component-tree.md `PipelineMap.tsx`)."""
    return {
        "nodes": [
            {
                "id": n.id,
                "type": n.node_type,
                "name": n.name,
                "lat": n.lat,
                "lon": n.lon,
                **n.metadata,
            }
            for n in graph.nodes
        ],
        "edges": [
            {
                "id": e.id,
                "type": e.edge_type,
                "from": e.from_node_id,
                "to": e.to_node_id,
                "capacity_bcf_d": e.capacity_bcf_d,
                "scheduled_flow_bcf_d": e.scheduled_flow_bcf_d,
                "actual_flow_bcf_d": e.actual_flow_bcf_d,
                "utilization": e.utilization,
                "direction": e.direction,
                "maintenance": e.maintenance,
                "constraint": e.constraint,
                "tariff": e.tariff,
                "basis_relationship": e.basis_relationship,
                "is_constrained": e.is_constrained,
            }
            for e in graph.edges
        ],
    }
