"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface ImpactEdge {
  sequence_index: number;
  category: string;
  from_node: string;
  to_node: string;
  description: string;
  confidence: number;
  magnitude: number | null;
}

interface ImpactAnalysis {
  id: string;
  signal_id: string;
  event_type: string;
  physical_impact: string;
  bullish_bearish: string;
  magnitude: number;
  confidence: number;
  portfolio_implications: string;
  risk_implications: string;
  uncertainties: string[];
  chain: ImpactEdge[];
  created_at: string;
}

const DIRECTION_COLOR: Record<string, string> = {
  BULLISH: "text-terminal-bull",
  BEARISH: "text-terminal-bear",
  NEUTRAL: "text-terminal-muted",
};

function ImpactChain({ analysis }: { analysis: ImpactAnalysis }) {
  return (
    <div className="panel">
      <div className="panel-title">
        {analysis.event_type} —{" "}
        <span className={DIRECTION_COLOR[analysis.bullish_bearish] ?? ""}>{analysis.bullish_bearish}</span>
      </div>
      <div className="text-[10px] text-terminal-muted mb-2">{analysis.physical_impact}</div>
      <ol className="flex flex-col gap-1.5 text-xs">
        {analysis.chain.map((edge) => (
          <li key={edge.sequence_index} className="border-l-2 border-terminal-border pl-2">
            <div className="text-terminal-muted text-[10px]">
              {edge.from_node} → {edge.to_node} (confidence {(edge.confidence * 100).toFixed(0)}%
              {edge.magnitude != null ? `, magnitude ${edge.magnitude.toFixed(0)}` : ""})
            </div>
            <div>{edge.description}</div>
          </li>
        ))}
      </ol>
      {analysis.uncertainties.length > 0 && (
        <div className="mt-2 text-[10px] text-terminal-warn">
          Uncertainties: {analysis.uncertainties.join("; ")}
        </div>
      )}
    </div>
  );
}

export function ImpactsTable() {
  const { token } = useAuth();
  const [impacts, setImpacts] = useState<ImpactAnalysis[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    apiGet<ImpactAnalysis[]>("/alpha/impacts?since_hours=24", token)
      .then(setImpacts)
      .catch(() =>
        setMessage("Unable to load AlphaImpact data — this requires the 'alpha_impacts.view' permission.")
      );
  }, [token]);

  if (message) return <p className="text-xs text-terminal-bear">{message}</p>;
  if (!impacts) return <p className="text-xs text-terminal-muted">Loading…</p>;

  const activeImpact = impacts.find((i) => i.id === selected) ?? impacts[0] ?? null;

  return (
    <div className="space-y-4">
      <h1 className="panel-title">AlphaImpact™ — What Each Signal Means</h1>
      <p className="text-[11px] text-terminal-muted">
        A causal chain from physical event to portfolio/risk implication for each material signal —
        magnitude and confidence decay along the chain rather than being independently modeled per
        stage (Milestone 2 scope).
      </p>
      {impacts.length === 0 ? (
        <div className="panel">
          <div className="text-xs text-terminal-muted">No impact analyses in the last 24 hours.</div>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="panel overflow-x-auto lg:col-span-1">
            <table className="mono-table w-full">
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Direction</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {impacts.map((i) => (
                  <tr key={i.id} className={i.id === activeImpact?.id ? "text-terminal-accent" : ""}>
                    <td className="whitespace-nowrap">{i.event_type}</td>
                    <td className={DIRECTION_COLOR[i.bullish_bearish] ?? ""}>{i.bullish_bearish}</td>
                    <td>
                      <button
                        onClick={() => setSelected(i.id)}
                        className="text-[10px] px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-accent"
                      >
                        View
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="lg:col-span-2">{activeImpact && <ImpactChain analysis={activeImpact} />}</div>
        </div>
      )}
    </div>
  );
}
