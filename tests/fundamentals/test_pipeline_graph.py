from fundamentals_service.pipeline_graph import (
    PipelineEdge,
    PipelineGraph,
    PipelineNode,
    build_default_pipeline_graph,
    to_geojson_like,
)


def test_default_graph_covers_every_node_type():
    graph = build_default_pipeline_graph()
    types = {n.node_type for n in graph.nodes}
    expected = {
        "production_basin",
        "processing_plant",
        "pipeline_interconnect",
        "storage_facility",
        "city_gate",
        "power_plant",
        "LNG_terminal",
        "export_point",
        "hub",
    }
    assert expected.issubset(types)


def test_default_graph_covers_every_edge_type():
    graph = build_default_pipeline_graph()
    types = {e.edge_type for e in graph.edges}
    assert {"pipeline", "transport_contract", "interconnect"}.issubset(types)


def test_every_edge_references_a_real_node():
    graph = build_default_pipeline_graph()
    node_ids = {n.id for n in graph.nodes}
    for edge in graph.edges:
        assert edge.from_node_id in node_ids
        assert edge.to_node_id in node_ids


def test_edge_utilization_computed_from_flow_and_capacity():
    edge = PipelineEdge("e1", "pipeline", "a", "b", capacity_bcf_d=4.0, scheduled_flow_bcf_d=3.0, actual_flow_bcf_d=3.0)
    assert edge.utilization == 0.75


def test_edge_utilization_zero_capacity_is_zero():
    edge = PipelineEdge("e1", "pipeline", "a", "b", capacity_bcf_d=0.0, scheduled_flow_bcf_d=0.0, actual_flow_bcf_d=0.0)
    assert edge.utilization == 0.0


def test_edge_is_constrained_by_high_utilization():
    edge = PipelineEdge("e1", "pipeline", "a", "b", capacity_bcf_d=4.0, scheduled_flow_bcf_d=3.8, actual_flow_bcf_d=3.8)
    assert edge.is_constrained


def test_edge_is_constrained_by_explicit_flag_even_at_low_utilization():
    edge = PipelineEdge(
        "e1", "pipeline", "a", "b", capacity_bcf_d=4.0, scheduled_flow_bcf_d=1.0, actual_flow_bcf_d=1.0,
        constraint="Planned maintenance reduces effective capacity",
    )
    assert edge.is_constrained


def test_graph_node_lookup():
    graph = build_default_pipeline_graph()
    node = graph.node("henry_hub")
    assert node is not None
    assert node.name == "Henry Hub"
    assert graph.node("does_not_exist") is None


def test_graph_edges_for_node():
    graph = build_default_pipeline_graph()
    edges = graph.edges_for("henry_hub")
    assert len(edges) > 0
    assert all("henry_hub" in (e.from_node_id, e.to_node_id) for e in edges)


def test_graph_average_utilization_matches_manual_calc():
    graph = PipelineGraph(
        nodes=[PipelineNode("a", "hub", "A", 0, 0), PipelineNode("b", "hub", "B", 0, 0)],
        edges=[
            PipelineEdge("e1", "pipeline", "a", "b", 4.0, 2.0, 2.0),
            PipelineEdge("e2", "pipeline", "a", "b", 2.0, 2.0, 2.0),
        ],
    )
    assert graph.average_utilization() == (0.5 + 1.0) / 2
    assert graph.total_capacity_bcf_d() == 6.0
    assert graph.total_actual_flow_bcf_d() == 4.0


def test_constrained_edges_filters_correctly():
    graph = PipelineGraph(
        nodes=[PipelineNode("a", "hub", "A", 0, 0), PipelineNode("b", "hub", "B", 0, 0)],
        edges=[
            PipelineEdge("loose", "pipeline", "a", "b", 10.0, 1.0, 1.0),
            PipelineEdge("tight", "pipeline", "a", "b", 10.0, 9.5, 9.5),
        ],
    )
    constrained = graph.constrained_edges()
    assert len(constrained) == 1
    assert constrained[0].id == "tight"


def test_to_geojson_like_serializes_nodes_and_edges():
    graph = build_default_pipeline_graph()
    payload = to_geojson_like(graph)
    assert len(payload["nodes"]) == len(graph.nodes)
    assert len(payload["edges"]) == len(graph.edges)
    assert {"id", "type", "name", "lat", "lon"}.issubset(payload["nodes"][0].keys())
    assert {"id", "type", "from", "to", "utilization", "is_constrained"}.issubset(payload["edges"][0].keys())
