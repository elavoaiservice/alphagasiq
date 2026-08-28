"""Enterprise Digital Twin overlay (docs/alpha-intelligence.md section 11.7,
Milestone 10): parses an organization's own `ASSET`/`FACILITY`-domain
`EnterpriseRecordRow`s into overlay points pinned onto the existing public
pipeline digital twin (`fundamentals_service.pipeline_graph.PipelineGraph`).

Pure -- no DB/LLM/event-bus access, the same discipline as every other engine
in this codebase.

Provisional decision (revisit once real customer asset data exists): a
record's `row_data` is assumed to carry `pipeline_node_id` (required -- the id
of an existing node in the public pipeline graph this asset should be pinned
to) and optionally `label`. There is no enforced schema for enterprise records
(docs/alpha-intelligence.md section 11.4: opaque JSON blob), so a record
missing `pipeline_node_id`, or naming a node id that doesn't exist in the
current graph, is skipped defensively rather than guessed at or placed at a
fabricated location."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PipelineOverlayPoint:
    dataset_id: str
    record_id: str
    pipeline_node_id: str
    label: str

    @staticmethod
    def from_record(
        *, dataset_id: str, record_id: str, row_data: dict[str, Any], known_node_ids: set[str]
    ) -> "PipelineOverlayPoint | None":
        node_id = row_data.get("pipeline_node_id")
        if not node_id or not isinstance(node_id, str) or node_id not in known_node_ids:
            return None
        label = row_data.get("label")
        if not isinstance(label, str) or not label:
            label = f"Record {record_id[:8]}"
        return PipelineOverlayPoint(dataset_id=dataset_id, record_id=record_id, pipeline_node_id=node_id, label=label)


def build_overlay(
    *, records_by_dataset: dict[str, list[dict[str, Any]]], known_node_ids: set[str]
) -> list[PipelineOverlayPoint]:
    """`records_by_dataset` maps dataset id -> that dataset's raw `EnterpriseRecordRow`
    dicts (each carrying `id`/`row_data`). Pure aggregation over
    `PipelineOverlayPoint.from_record`."""
    points: list[PipelineOverlayPoint] = []
    for dataset_id, records in records_by_dataset.items():
        for record in records:
            point = PipelineOverlayPoint.from_record(
                dataset_id=dataset_id, record_id=record["id"], row_data=record["row_data"], known_node_ids=known_node_ids
            )
            if point is not None:
                points.append(point)
    return points
