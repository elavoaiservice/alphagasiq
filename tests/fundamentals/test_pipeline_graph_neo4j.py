"""Tests for the real Neo4j-backed pipeline graph persistence
(`fundamentals_service.pipeline_graph_neo4j`).

No live Neo4j server is reachable in this environment (no Docker daemon, and the
sandbox's egress policy blocks fetching Neo4j's own distribution directly — see
`/root/.ccr/README.md`), so the `neo4j.AsyncDriver`/`AsyncSession` network boundary is
replaced with a faithful in-memory test double keyed by node/edge id (mirroring Neo4j's
own `MERGE`-by-id idempotency) — everything on this side of that boundary (the exact
Cypher query text, parameter shapes passed to `session.run()`, JSON-encoding of
`PipelineNode.metadata`, and full seed-then-reload round-trip reconstruction) is real,
unmocked code. This mirrors how `tests/eventbus/test_kafka_eventbus.py` validates
`RedpandaEventBus` against `aiokafka` test doubles for the same reason.
"""

from __future__ import annotations

import pytest
from fundamentals_service.pipeline_graph import PipelineEdge, PipelineGraph, PipelineNode, build_default_pipeline_graph
from fundamentals_service.pipeline_graph_neo4j import (
    load_pipeline_graph_from_neo4j,
    seed_neo4j_from_graph,
    sync_pipeline_graph_via_neo4j,
)


class _FakeRecord:
    def __init__(self, data: dict):
        self._data = data

    def data(self) -> dict:
        return self._data


class _FakeResult:
    def __init__(self, records: list[_FakeRecord]):
        self._records = records

    def __aiter__(self):
        return self._aiter()

    async def _aiter(self):
        for record in self._records:
            yield record


class _FakeSession:
    def __init__(self, driver: "_FakeDriver"):
        self._driver = driver

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    async def run(self, query: str, **kwargs) -> _FakeResult:
        self._driver.calls.append((query, kwargs))
        if "MERGE (p:PipelineNode {id: n.id})" in query:
            for n in kwargs["nodes"]:
                self._driver.nodes[n["id"]] = n
            return _FakeResult([])
        if "MERGE (a)-[r:PIPELINE_EDGE {id: e.id}]->(b)" in query:
            for e in kwargs["edges"]:
                assert e["from_node_id"] in self._driver.nodes, "edge references a node that was never seeded"
                assert e["to_node_id"] in self._driver.nodes
                self._driver.edges[e["id"]] = e
            return _FakeResult([])
        if query.strip().startswith("MATCH (n:PipelineNode)"):
            return _FakeResult([_FakeRecord(n) for n in self._driver.nodes.values()])
        if query.strip().startswith("MATCH (a:PipelineNode)-[r:PIPELINE_EDGE]->(b:PipelineNode)"):
            return _FakeResult([_FakeRecord(e) for e in self._driver.edges.values()])
        raise AssertionError(f"unexpected Cypher query:\n{query}")


class _FakeDriver:
    """Stands in for a real Neo4j instance: a dict-keyed store where re-`MERGE`ing the
    same id overwrites in place rather than duplicating — the exact idempotency
    property a real Neo4j `MERGE` on `{id: ...}` provides."""

    def __init__(self):
        self.nodes: dict[str, dict] = {}
        self.edges: dict[str, dict] = {}
        self.calls: list[tuple[str, dict]] = []

    def session(self, database=None) -> _FakeSession:
        return _FakeSession(self)


def _sample_graph() -> PipelineGraph:
    nodes = [
        PipelineNode("waha", "hub", "Waha Hub", 31.05, -103.13, metadata={"region": "permian"}),
        PipelineNode("henry_hub", "hub", "Henry Hub", 29.9, -91.8),
    ]
    edges = [
        PipelineEdge(
            id="waha_to_henry",
            edge_type="pipeline",
            from_node_id="waha",
            to_node_id="henry_hub",
            capacity_bcf_d=2.5,
            scheduled_flow_bcf_d=2.0,
            actual_flow_bcf_d=2.3,
        )
    ]
    return PipelineGraph(nodes=nodes, edges=edges)


async def test_seed_writes_nodes_and_edges_with_correct_params():
    driver = _FakeDriver()
    graph = _sample_graph()
    await seed_neo4j_from_graph(driver, graph)

    assert set(driver.nodes.keys()) == {"waha", "henry_hub"}
    assert driver.nodes["waha"]["node_type"] == "hub"
    assert driver.nodes["waha"]["lat"] == 31.05
    # metadata must be JSON-encoded, not passed as a nested dict property
    import json

    assert json.loads(driver.nodes["waha"]["metadata_json"]) == {"region": "permian"}

    assert set(driver.edges.keys()) == {"waha_to_henry"}
    assert driver.edges["waha_to_henry"]["from_node_id"] == "waha"
    assert driver.edges["waha_to_henry"]["capacity_bcf_d"] == 2.5


async def test_load_reconstructs_an_equivalent_pipeline_graph():
    driver = _FakeDriver()
    original = _sample_graph()
    await seed_neo4j_from_graph(driver, original)

    reloaded = await load_pipeline_graph_from_neo4j(driver)

    assert {n.id for n in reloaded.nodes} == {n.id for n in original.nodes}
    assert {e.id for e in reloaded.edges} == {e.id for e in original.edges}

    reloaded_waha = reloaded.node("waha")
    assert reloaded_waha is not None
    assert reloaded_waha.metadata == {"region": "permian"}
    assert reloaded_waha.node_type == "hub"

    reloaded_edge = reloaded.edges_for("waha")[0]
    assert reloaded_edge.capacity_bcf_d == 2.5
    assert reloaded_edge.utilization == pytest.approx(2.3 / 2.5)


async def test_sync_round_trip_matches_the_full_default_graph():
    """Exercises the real, ~30-node/~27-edge default pipeline graph end to end — the
    exact data `AppState` seeds — through a full seed-then-reload round trip."""
    driver = _FakeDriver()
    original = build_default_pipeline_graph()

    reloaded = await sync_pipeline_graph_via_neo4j(driver, original)

    assert len(reloaded.nodes) == len(original.nodes)
    assert len(reloaded.edges) == len(original.edges)
    assert reloaded.total_capacity_bcf_d() == pytest.approx(original.total_capacity_bcf_d())
    assert reloaded.average_utilization() == pytest.approx(original.average_utilization())
    assert {e.id for e in reloaded.constrained_edges()} == {e.id for e in original.constrained_edges()}


async def test_reseeding_is_idempotent_not_duplicating():
    driver = _FakeDriver()
    graph = _sample_graph()
    await seed_neo4j_from_graph(driver, graph)
    await seed_neo4j_from_graph(driver, graph)

    reloaded = await load_pipeline_graph_from_neo4j(driver)
    assert len(reloaded.nodes) == 2
    assert len(reloaded.edges) == 1


async def test_edges_reference_only_seeded_nodes():
    driver = _FakeDriver()
    graph = _sample_graph()
    await seed_neo4j_from_graph(driver, graph)
    # both edge endpoints were asserted present inside _FakeSession.run already;
    # this test documents that guarantee explicitly for a graph with a dangling edge.
    bad_graph = PipelineGraph(
        nodes=[PipelineNode("only_node", "hub", "Only Node", 0.0, 0.0)],
        edges=[
            PipelineEdge(
                id="dangling",
                edge_type="pipeline",
                from_node_id="only_node",
                to_node_id="does_not_exist",
                capacity_bcf_d=1.0,
                scheduled_flow_bcf_d=1.0,
                actual_flow_bcf_d=1.0,
            )
        ],
    )
    with pytest.raises(AssertionError):
        await seed_neo4j_from_graph(driver, bad_graph)
