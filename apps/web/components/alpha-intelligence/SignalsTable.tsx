"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface Signal {
  id: string;
  signal_type: string;
  category: string;
  headline: string;
  description: string;
  market: string;
  materiality_score: number;
  confidence: number;
  direction: string;
  detected_at: string;
}

const DIRECTION_COLOR: Record<string, string> = {
  BULLISH: "text-terminal-bull",
  BEARISH: "text-terminal-bear",
  NEUTRAL: "text-terminal-muted",
};

function materialityLabel(score: number): string {
  if (score >= 90) return "CRITICAL";
  if (score >= 75) return "HIGH";
  if (score >= 60) return "MODERATE";
  return "LOW";
}

export function SignalsTable() {
  const { token } = useAuth();
  const [signals, setSignals] = useState<Signal[] | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    apiGet<Signal[]>("/alpha/signals?since_hours=24", token)
      .then(setSignals)
      .catch(() =>
        setMessage(
          "Unable to load AlphaSignal data — this requires the 'alpha_signals.view' permission."
        )
      );
  }, [token]);

  if (message) return <p className="text-xs text-terminal-bear">{message}</p>;
  if (!signals) return <p className="text-xs text-terminal-muted">Loading…</p>;

  return (
    <div className="space-y-4">
      <h1 className="panel-title">AlphaSignal™ — Material Market Changes</h1>
      <p className="text-[11px] text-terminal-muted">
        Ranked by materiality (magnitude, historical rarity, confidence, and data quality) — not
        every change, only the ones that clear a deterministic threshold. Last 24 hours.
      </p>
      {signals.length === 0 ? (
        <div className="panel">
          <div className="text-xs text-terminal-muted">
            No material changes detected in the last 24 hours.
          </div>
        </div>
      ) : (
        <div className="panel overflow-x-auto">
          <table className="mono-table w-full">
            <thead>
              <tr>
                <th>Materiality</th>
                <th>Type</th>
                <th>Headline</th>
                <th>Direction</th>
                <th>Confidence</th>
                <th>Detected At</th>
              </tr>
            </thead>
            <tbody>
              {signals.map((s) => (
                <tr key={s.id}>
                  <td className="whitespace-nowrap">
                    {s.materiality_score.toFixed(0)} ({materialityLabel(s.materiality_score)})
                  </td>
                  <td className="whitespace-nowrap">{s.signal_type}</td>
                  <td>
                    <div>{s.headline}</div>
                    <div className="text-[10px] text-terminal-muted">{s.description}</div>
                  </td>
                  <td className={DIRECTION_COLOR[s.direction] ?? ""}>{s.direction}</td>
                  <td>{(s.confidence * 100).toFixed(0)}%</td>
                  <td className="whitespace-nowrap">{new Date(s.detected_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
