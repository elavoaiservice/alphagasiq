"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api-client";

interface NodeEdge {
  id: string;
  type: string;
  from: string;
  to: string;
  capacity_bcf_d: number;
  actual_flow_bcf_d: number;
  utilization: number;
  maintenance: string | null;
  constraint: string | null;
  basis_relationship: string | null;
  is_constrained: boolean;
}

interface NodeDetail {
  node: { id: string; type: string; name: string; lat: number; lon: number };
  edges: NodeEdge[];
}

export function PipelineNodeInspector({ nodeId, onClose }: { nodeId: string; onClose: () => void }) {
  const [detail, setDetail] = useState<NodeDetail | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiGet<NodeDetail>(`/fundamentals/pipeline/nodes/${nodeId}`)
      .then((d) => !cancelled && setDetail(d))
      .catch(() => !cancelled && setDetail(null));
    return () => {
      cancelled = true;
    };
  }, [nodeId]);

  return (
    <div className="panel w-72 shrink-0">
      <div className="flex items-center justify-between">
        <div className="panel-title">Node Inspector</div>
        <button onClick={onClose} className="text-terminal-muted hover:text-terminal-text text-xs">
          ✕
        </button>
      </div>
      {!detail ? (
        <div className="text-xs text-terminal-muted">Loading...</div>
      ) : (
        <>
          <div className="text-sm text-terminal-text">{detail.node.name}</div>
          <div className="text-[10px] text-terminal-muted mb-2">{detail.node.type}</div>
          <div className="space-y-2">
            {detail.edges.map((e) => (
              <div
                key={e.id}
                className={`text-xs border rounded p-1.5 ${
                  e.is_constrained ? "border-terminal-warn text-terminal-warn" : "border-terminal-border text-terminal-text"
                }`}
              >
                <div className="font-mono">
                  {e.from} → {e.to} ({e.type})
                </div>
                <div className="text-terminal-muted">
                  {e.actual_flow_bcf_d.toFixed(2)} / {e.capacity_bcf_d.toFixed(2)} Bcf/d ·{" "}
                  {(e.utilization * 100).toFixed(0)}% utilized
                </div>
                {e.maintenance && <div>⚠ {e.maintenance}</div>}
                {e.constraint && <div>⚠ {e.constraint}</div>}
                {e.basis_relationship && <div className="text-terminal-accent">{e.basis_relationship}</div>}
              </div>
            ))}
            {detail.edges.length === 0 && <div className="text-xs text-terminal-muted">No connected corridors.</div>}
          </div>
        </>
      )}
    </div>
  );
}
