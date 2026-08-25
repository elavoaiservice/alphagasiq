"use client";

import { useEffect, useState } from "react";
import { API_BASE } from "@/lib/api-client";
import { project } from "./projection";
import { PipelineNodeInspector } from "./PipelineNodeInspector";

interface GraphNode {
  id: string;
  type: string;
  name: string;
  lat: number;
  lon: number;
}

interface GraphEdge {
  id: string;
  type: string;
  from: string;
  to: string;
  capacity_bcf_d: number;
  actual_flow_bcf_d: number;
  utilization: number;
  maintenance: string | null;
  constraint: string | null;
  is_constrained: boolean;
}

interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  classification: string;
}

const WIDTH = 900;
const HEIGHT = 520;

const NODE_COLORS: Record<string, string> = {
  production_basin: "#e0a941",
  processing_plant: "#7c8798",
  pipeline_interconnect: "#7c8798",
  storage_facility: "#3fb6a8",
  city_gate: "#d5dae3",
  power_plant: "#e5534b",
  LNG_terminal: "#3ecf8e",
  export_point: "#a988ff",
  hub: "#3fb6a8",
};

export function PipelineMap() {
  const [graph, setGraph] = useState<GraphResponse | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/fundamentals/pipeline/graph`)
      .then((r) => r.json())
      .then((d) => !cancelled && setGraph(d))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  if (!graph) {
    return (
      <div className="panel">
        <div className="panel-title">Pipeline Digital Twin</div>
        <div className="text-xs text-terminal-muted">Loading network...</div>
      </div>
    );
  }

  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));

  return (
    <div className="flex gap-3">
      <div className="panel flex-1">
        <div className="flex items-center justify-between mb-1">
          <div className="panel-title mb-0">Pipeline Digital Twin — U.S. Infrastructure (simplified projection)</div>
          <span className="text-[10px] px-1.5 py-0.5 border border-terminal-muted text-terminal-muted rounded">
            {graph.classification}
          </span>
        </div>
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="w-full h-auto bg-terminal-bg rounded">
          {graph.edges.map((e) => {
            const from = nodeById.get(e.from);
            const to = nodeById.get(e.to);
            if (!from || !to) return null;
            const p1 = project(from.lat, from.lon, WIDTH, HEIGHT);
            const p2 = project(to.lat, to.lon, WIDTH, HEIGHT);
            const strokeWidth = 1 + Math.min(4, e.capacity_bcf_d / 1.5);
            const color = e.is_constrained ? "#e0a941" : e.maintenance ? "#e5534b" : "#2a3644";
            return (
              <line
                key={e.id}
                x1={p1.x}
                y1={p1.y}
                x2={p2.x}
                y2={p2.y}
                stroke={color}
                strokeWidth={strokeWidth}
                opacity={hovered && hovered !== e.from && hovered !== e.to ? 0.25 : 0.85}
              >
                <title>
                  {e.from} → {e.to}: {e.actual_flow_bcf_d.toFixed(2)}/{e.capacity_bcf_d.toFixed(2)} Bcf/d (
                  {(e.utilization * 100).toFixed(0)}%){e.constraint ? ` — ${e.constraint}` : ""}
                  {e.maintenance ? ` — ${e.maintenance}` : ""}
                </title>
              </line>
            );
          })}
          {graph.nodes.map((n) => {
            const p = project(n.lat, n.lon, WIDTH, HEIGHT);
            const color = NODE_COLORS[n.type] ?? "#d5dae3";
            const isSelected = selected === n.id;
            return (
              <g
                key={n.id}
                onClick={() => setSelected(n.id)}
                onMouseEnter={() => setHovered(n.id)}
                onMouseLeave={() => setHovered(null)}
                style={{ cursor: "pointer" }}
              >
                <circle
                  cx={p.x}
                  cy={p.y}
                  r={isSelected ? 7 : 5}
                  fill={color}
                  stroke={isSelected ? "#ffffff" : "#0a0e14"}
                  strokeWidth={isSelected ? 2 : 1}
                >
                  <title>{n.name}</title>
                </circle>
                <text x={p.x + 8} y={p.y + 3} fontSize={9} fill="#7c8798">
                  {n.name}
                </text>
              </g>
            );
          })}
        </svg>
        <div className="mt-2 flex flex-wrap gap-3 text-[10px] text-terminal-muted">
          {Object.entries(NODE_COLORS)
            .filter(([type]) => graph.nodes.some((n) => n.type === type))
            .map(([type, color]) => (
              <span key={type} className="flex items-center gap-1">
                <span className="inline-block w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
                {type}
              </span>
            ))}
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-0.5" style={{ backgroundColor: "#e0a941" }} /> constrained corridor
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-0.5" style={{ backgroundColor: "#e5534b" }} /> under maintenance
          </span>
        </div>
      </div>
      {selected && <PipelineNodeInspector nodeId={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
