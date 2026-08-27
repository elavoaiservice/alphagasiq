"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface ConsensusWeight {
  agent_type: string;
  weight: number;
  alpha_score: number;
  forecast_confidence: number;
  direction: string;
}

interface ConsensusView {
  id: string;
  consensus_type: string;
  market: string;
  target: string;
  horizon: string;
  consensus_value: number | null;
  bull_probability: number;
  bear_probability: number;
  neutral_probability: number;
  confidence: number;
  dispersion: number;
  agreement_label: string;
  agent_count: number;
  agent_weights: ConsensusWeight[];
  leading_agents: string[];
  dissenting_agents: string[];
  drivers: string[];
  risks: string[];
  market_consensus_value: number | null;
  variance_vs_market: number | null;
  created_at: string;
}

const DIRECTION_COLOR: Record<string, string> = {
  BULLISH: "text-terminal-bull",
  BEARISH: "text-terminal-bear",
  NEUTRAL: "text-terminal-muted",
};

const AGREEMENT_COLOR: Record<string, string> = {
  HIGH: "text-terminal-bull",
  MODERATE: "text-terminal-warn",
  LOW: "text-terminal-bear",
};

function ProbabilityBar({ view }: { view: ConsensusView }) {
  const bull = Math.round(view.bull_probability * 100);
  const bear = Math.round(view.bear_probability * 100);
  const neutral = Math.max(0, 100 - bull - bear);
  return (
    <div className="flex h-2.5 w-full overflow-hidden rounded border border-terminal-border">
      <div className="bg-terminal-bull" style={{ width: `${bull}%` }} title={`Bull ${bull}%`} />
      <div className="bg-terminal-muted" style={{ width: `${neutral}%` }} title={`Neutral ${neutral}%`} />
      <div className="bg-terminal-bear" style={{ width: `${bear}%` }} title={`Bear ${bear}%`} />
    </div>
  );
}

function ConsensusDetail({ view }: { view: ConsensusView }) {
  return (
    <div className="panel">
      <div className="panel-title">
        {view.consensus_type} — {view.market}
        {view.target ? ` (${view.target})` : ""}{" "}
        <span className={AGREEMENT_COLOR[view.agreement_label] ?? ""}>{view.agreement_label} agreement</span>
      </div>
      <div className="text-[10px] text-terminal-muted mb-2">
        {view.agent_count} contributing agents · dispersion {view.dispersion.toFixed(2)} · confidence{" "}
        {(view.confidence * 100).toFixed(0)}%
      </div>

      <ProbabilityBar view={view} />
      <div className="flex justify-between text-[10px] text-terminal-muted mt-1 mb-3">
        <span className="text-terminal-bull">Bull {(view.bull_probability * 100).toFixed(0)}%</span>
        <span>Neutral {(view.neutral_probability * 100).toFixed(0)}%</span>
        <span className="text-terminal-bear">Bear {(view.bear_probability * 100).toFixed(0)}%</span>
      </div>

      {view.consensus_value != null && (
        <div className="text-xs mb-3">
          AlphaConsensus™ value: <span className="text-terminal-accent">{view.consensus_value.toFixed(1)}</span>
          {view.market_consensus_value != null && (
            <>
              {" "}
              vs. market consensus {view.market_consensus_value.toFixed(1)}
              {view.variance_vs_market != null && (
                <span className={view.variance_vs_market >= 0 ? "text-terminal-bull" : "text-terminal-bear"}>
                  {" "}
                  ({view.variance_vs_market >= 0 ? "+" : ""}
                  {view.variance_vs_market.toFixed(1)})
                </span>
              )}
            </>
          )}
        </div>
      )}

      <table className="mono-table w-full mb-3">
        <thead>
          <tr>
            <th>Agent</th>
            <th>Weight</th>
            <th>Alpha Score™</th>
            <th>Direction</th>
          </tr>
        </thead>
        <tbody>
          {view.agent_weights.map((w) => (
            <tr key={w.agent_type}>
              <td className="whitespace-nowrap">{w.agent_type}</td>
              <td>{(w.weight * 100).toFixed(0)}%</td>
              <td>{w.alpha_score.toFixed(0)}</td>
              <td className={DIRECTION_COLOR[w.direction] ?? ""}>{w.direction}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {view.leading_agents.length > 0 && (
        <div className="text-[10px] text-terminal-muted mb-1">
          Leading agents: {view.leading_agents.join(", ")}
        </div>
      )}
      {view.dissenting_agents.length > 0 && (
        <div className="text-[10px] text-terminal-warn mb-1">
          Dissenting agents: {view.dissenting_agents.join(", ")}
        </div>
      )}
      {view.drivers.length > 0 && (
        <div className="text-[10px] text-terminal-muted mt-2">Drivers: {view.drivers.join("; ")}</div>
      )}
      {view.risks.length > 0 && (
        <div className="text-[10px] text-terminal-bear mt-1">Risks: {view.risks.join("; ")}</div>
      )}
    </div>
  );
}

export function ConsensusTable() {
  const { token } = useAuth();
  const [views, setViews] = useState<ConsensusView[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    apiGet<ConsensusView[]>("/alpha/consensus?since_hours=24", token)
      .then(setViews)
      .catch(() =>
        setMessage("Unable to load AlphaConsensus data — this requires the 'alpha_consensus.view' permission.")
      );
  }, [token]);

  if (message) return <p className="text-xs text-terminal-bear">{message}</p>;
  if (!views) return <p className="text-xs text-terminal-muted">Loading…</p>;

  const activeView = views.find((v) => v.id === selected) ?? views[0] ?? null;

  return (
    <div className="space-y-4">
      <h1 className="panel-title">AlphaConsensus™ — Do the Agents Agree?</h1>
      <p className="text-[11px] text-terminal-muted">
        Each contributing agent&apos;s forecast is weighted by its Agent Alpha Score™ — a
        calibration-derived weight, not a simple majority vote — to produce a single dynamically-weighted
        consensus view per market/target.
      </p>
      {views.length === 0 ? (
        <div className="panel">
          <div className="text-xs text-terminal-muted">No consensus views in the last 24 hours.</div>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="panel overflow-x-auto lg:col-span-1">
            <table className="mono-table w-full">
              <thead>
                <tr>
                  <th>Market</th>
                  <th>Agreement</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {views.map((v) => (
                  <tr key={v.id} className={v.id === activeView?.id ? "text-terminal-accent" : ""}>
                    <td className="whitespace-nowrap">
                      {v.market}
                      {v.target ? ` · ${v.target}` : ""}
                    </td>
                    <td className={AGREEMENT_COLOR[v.agreement_label] ?? ""}>{v.agreement_label}</td>
                    <td>
                      <button
                        onClick={() => setSelected(v.id)}
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
          <div className="lg:col-span-2">{activeView && <ConsensusDetail view={activeView} />}</div>
        </div>
      )}
    </div>
  );
}
