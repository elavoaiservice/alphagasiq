from __future__ import annotations

from agent_sdk import AgentOutcome, BaseAgent, LLMMessage
from fundamentals_service.pipeline_graph import PipelineGraph
from schemas import AgentStatus, AgentType, Citation, DataClassification, DataSourceRef


class PipelineAgent(BaseAgent):
    """Fundamental Research Team: reads the pipeline digital twin and surfaces
    constrained corridors, maintenance events, and basis-relevant flow shifts.

    All figures come from the graph passed in (`services/fundamentals/.../
    pipeline_graph.py`), which is SIMULATED seed data standing in for the FERC /
    pipeline-bulletin-board connectors described in docs/data-sources.md — no figure
    here is invented by the LLM.
    """

    agent_id = "fundamentals.pipeline.v1"
    agent_name = "Pipeline Agent"
    agent_type = AgentType.PIPELINE
    version = "0.1.0"

    async def _execute(self, *, graph: PipelineGraph, is_simulated: bool = True) -> AgentOutcome:
        if not graph.edges:
            return AgentOutcome(status=AgentStatus.SKIPPED, reasoning_summary="Pipeline graph has no edges to analyze.")

        constrained = graph.constrained_edges()
        maintenance_events = [e for e in graph.edges if e.maintenance]

        outputs = {
            "total_capacity_bcf_d": graph.total_capacity_bcf_d(),
            "total_actual_flow_bcf_d": graph.total_actual_flow_bcf_d(),
            "average_utilization": graph.average_utilization(),
            "constrained_corridor_count": len(constrained),
            "constrained_corridors": [
                {
                    "id": e.id,
                    "from": e.from_node_id,
                    "to": e.to_node_id,
                    "utilization": e.utilization,
                    "constraint": e.constraint,
                    "basis_relationship": e.basis_relationship,
                }
                for e in constrained
            ],
            "maintenance_events": [
                {"id": e.id, "from": e.from_node_id, "to": e.to_node_id, "maintenance": e.maintenance}
                for e in maintenance_events
            ],
        }

        classification = DataClassification.SIMULATED if is_simulated else DataClassification.PUBLIC
        source_name = "Pipeline digital twin (seed/simulated)" if is_simulated else "Pipeline bulletin boards"

        prompt = (
            f"Network average utilization is {graph.average_utilization():.1%} across {len(graph.edges)} "
            f"corridors, with {len(constrained)} constrained and {len(maintenance_events)} under maintenance. "
            "Summarize the pipeline-network picture in two sentences for a trading desk."
        )
        llm_response = await self.llm.complete([LLMMessage(role="user", content=prompt)])

        reasoning = (
            f"{len(constrained)} corridor(s) are constrained (>=90% utilized or flagged) out of "
            f"{len(graph.edges)}; {len(maintenance_events)} maintenance event(s) active. "
            f"{llm_response.content}"
        )

        return AgentOutcome(
            outputs=outputs,
            reasoning_summary=reasoning,
            confidence=0.7,
            tools=["fundamentals_service.pipeline_graph"],
            data_sources=[DataSourceRef(provider_id="pipeline_bulletin_board", classification=classification)],
            citations=[Citation(source=source_name, reference="pipeline_digital_twin", classification=classification)],
        )
