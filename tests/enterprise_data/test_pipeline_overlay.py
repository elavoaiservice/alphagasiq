"""Enterprise Digital Twin overlay (docs/alpha-intelligence.md section 11.7,
Milestone 10): `PipelineOverlayPoint.from_record`/`build_overlay` -- pure parsing
of an organization's own ASSET/FACILITY-domain enterprise records into points
pinned onto the public pipeline digital twin."""

from __future__ import annotations

from enterprise_data_service.pipeline_overlay import PipelineOverlayPoint, build_overlay


def test_from_record_pins_a_known_node():
    point = PipelineOverlayPoint.from_record(
        dataset_id="d1", record_id="r1", row_data={"pipeline_node_id": "permian", "label": "My Well Pad"},
        known_node_ids={"permian", "waha"},
    )
    assert point is not None
    assert point.pipeline_node_id == "permian"
    assert point.label == "My Well Pad"


def test_from_record_defaults_label_when_missing():
    point = PipelineOverlayPoint.from_record(
        dataset_id="d1", record_id="record-1234", row_data={"pipeline_node_id": "permian"}, known_node_ids={"permian"}
    )
    assert point is not None
    assert point.label == "Record record-1"


def test_from_record_returns_none_when_node_id_missing():
    assert (
        PipelineOverlayPoint.from_record(dataset_id="d1", record_id="r1", row_data={}, known_node_ids={"permian"})
        is None
    )


def test_from_record_returns_none_when_node_id_unknown():
    assert (
        PipelineOverlayPoint.from_record(
            dataset_id="d1", record_id="r1", row_data={"pipeline_node_id": "nonexistent"}, known_node_ids={"permian"}
        )
        is None
    )


def test_build_overlay_aggregates_across_datasets_and_skips_invalid_records():
    records_by_dataset = {
        "d1": [
            {"id": "r1", "row_data": {"pipeline_node_id": "permian", "label": "Asset A"}},
            {"id": "r2", "row_data": {"pipeline_node_id": "unknown-node"}},
        ],
        "d2": [
            {"id": "r3", "row_data": {"pipeline_node_id": "waha", "label": "Asset B"}},
            {"id": "r4", "row_data": {}},
        ],
    }
    points = build_overlay(records_by_dataset=records_by_dataset, known_node_ids={"permian", "waha"})
    assert {p.record_id for p in points} == {"r1", "r3"}
