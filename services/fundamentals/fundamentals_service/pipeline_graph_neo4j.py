"""Real Neo4j-backed persistence for the pipeline digital twin
(`pipeline_graph.py`'s docstring names this as the eventual migration target for the
in-memory/relational graph model).

`PipelineGraph`/`PipelineNode`/`PipelineEdge` stay the app-facing data model — nothing
that reads `state.pipeline_graph` needs to change. This module adds a real round trip
through Neo4j behind that same model: `seed_neo4j_from_graph()` writes a `PipelineGraph`
into Neo4j via Cypher `MERGE`, and `load_pipeline_graph_from_neo4j()` reads it back out,
reconstructing an equivalent `PipelineGraph`. `AppState` uses this round trip (seed, then
reload) only when `NEO4J_URI` is configured — the same additive, config-gated pattern as
`OIDC_ISSUER_URL` and `EVENT_BUS_IMPL=redpanda` elsewhere in this codebase; every default
dev/docker environment leaves it unset and keeps using the plain in-memory graph.

Modeling note: Neo4j node/relationship properties must be primitives or arrays of
primitives, not nested maps — `PipelineNode.metadata` (an arbitrary dict) is therefore
stored as a JSON string property (`metadata_json`) and decoded back on read, rather than
flattened into ad-hoc properties that would need to track `pipeline_graph.py`'s metadata
shape.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from neo4j import AsyncDriver

from .pipeline_graph import PipelineEdge, PipelineGraph, PipelineNode

_SEED_NODES_QUERY = """
UNWIND $nodes AS n
MERGE (p:PipelineNode {id: n.id})
SET p.node_type = n.node_type, p.name = n.name, p.lat = n.lat, p.lon = n.lon,
    p.metadata_json = n.metadata_json
"""

_SEED_EDGES_QUERY = """
UNWIND $edges AS e
MATCH (a:PipelineNode {id: e.from_node_id}), (b:PipelineNode {id: e.to_node_id})
MERGE (a)-[r:PIPELINE_EDGE {id: e.id}]->(b)
SET r.edge_type = e.edge_type, r.capacity_bcf_d = e.capacity_bcf_d,
    r.scheduled_flow_bcf_d = e.scheduled_flow_bcf_d, r.actual_flow_bcf_d = e.actual_flow_bcf_d,
    r.direction = e.direction, r.maintenance = e.maintenance, r.constraint = e.constraint,
    r.tariff = e.tariff, r.basis_relationship = e.basis_relationship
"""

_LOAD_NODES_QUERY = """
MATCH (n:PipelineNode)
RETURN n.id AS id, n.node_type AS node_type, n.name AS name, n.lat AS lat, n.lon AS lon,
       n.metadata_json AS metadata_json
"""

_LOAD_EDGES_QUERY = """
MATCH (a:PipelineNode)-[r:PIPELINE_EDGE]->(b:PipelineNode)
RETURN r.id AS id, r.edge_type AS edge_type, a.id AS from_node_id, b.id AS to_node_id,
       r.capacity_bcf_d AS capacity_bcf_d, r.scheduled_flow_bcf_d AS scheduled_flow_bcf_d,
       r.actual_flow_bcf_d AS actual_flow_bcf_d, r.direction AS direction,
       r.maintenance AS maintenance, r.constraint AS constraint, r.tariff AS tariff,
       r.basis_relationship AS basis_relationship
"""


def _node_to_params(node: PipelineNode) -> dict:
    return {
        "id": node.id,
        "node_type": node.node_type,
        "name": node.name,
        "lat": node.lat,
        "lon": node.lon,
        "metadata_json": json.dumps(node.metadata),
    }


def _edge_to_params(edge: PipelineEdge) -> dict:
    return asdict(edge)


async def seed_neo4j_from_graph(driver: AsyncDriver, graph: PipelineGraph, *, database: str | None = None) -> None:
    """Writes every node and edge in `graph` into Neo4j (idempotent — `MERGE` on each
    node/edge id, safe to re-run on every app boot without duplicating anything)."""
    async with driver.session(database=database) as session:
        await session.run(_SEED_NODES_QUERY, nodes=[_node_to_params(n) for n in graph.nodes])
        await session.run(_SEED_EDGES_QUERY, edges=[_edge_to_params(e) for e in graph.edges])


async def load_pipeline_graph_from_neo4j(driver: AsyncDriver, *, database: str | None = None) -> PipelineGraph:
    """Reconstructs a `PipelineGraph` from whatever is currently stored in Neo4j."""
    async with driver.session(database=database) as session:
        node_result = await session.run(_LOAD_NODES_QUERY)
        node_records = [record.data() async for record in node_result]
        edge_result = await session.run(_LOAD_EDGES_QUERY)
        edge_records = [record.data() async for record in edge_result]

    nodes = [
        PipelineNode(
            id=r["id"],
            node_type=r["node_type"],
            name=r["name"],
            lat=r["lat"],
            lon=r["lon"],
            metadata=json.loads(r["metadata_json"]) if r["metadata_json"] else {},
        )
        for r in node_records
    ]
    edges = [
        PipelineEdge(
            id=r["id"],
            edge_type=r["edge_type"],
            from_node_id=r["from_node_id"],
            to_node_id=r["to_node_id"],
            capacity_bcf_d=r["capacity_bcf_d"],
            scheduled_flow_bcf_d=r["scheduled_flow_bcf_d"],
            actual_flow_bcf_d=r["actual_flow_bcf_d"],
            direction=r["direction"],
            maintenance=r["maintenance"],
            constraint=r["constraint"],
            tariff=r["tariff"],
            basis_relationship=r["basis_relationship"],
        )
        for r in edge_records
    ]
    return PipelineGraph(nodes=nodes, edges=edges)


async def sync_pipeline_graph_via_neo4j(
    driver: AsyncDriver, graph: PipelineGraph, *, database: str | None = None
) -> PipelineGraph:
    """Seeds `graph` into Neo4j, then reads it back — a real round trip proving the
    Neo4j-backed path actually works end to end, not just that either half compiles.
    The returned `PipelineGraph` is equivalent to `graph` (same nodes/edges/fields);
    `AppState` uses this in place of assigning `graph` directly when Neo4j is
    configured, so `state.pipeline_graph` genuinely came from Neo4j."""
    await seed_neo4j_from_graph(driver, graph, database=database)
    return await load_pipeline_graph_from_neo4j(driver, database=database)
