"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface IntelligenceBrief {
  id: string;
  market: string;
  period_start: string;
  period_end: string;
  headline: string;
  summary: string;
  top_signals: unknown[];
  top_impacts: unknown[];
  consensus_highlights: unknown[];
  notable_scenario_runs: unknown[];
  pending_lessons: unknown[];
  generated_at: string;
}

const COMPONENTS = [
  {
    href: "/platform/alpha-intelligence/signals",
    label: "AlphaSignal™",
    description: "Material changes detected across the natural gas ecosystem, ranked by materiality.",
  },
  {
    href: "/platform/alpha-intelligence/impacts",
    label: "AlphaImpact™",
    description: "Causal chains from physical event to portfolio/risk implication for each signal.",
  },
  {
    href: "/platform/alpha-intelligence/consensus",
    label: "AlphaConsensus™",
    description: "Dynamically-weighted agent forecasts, aggregated with Agent Alpha Score™.",
  },
  {
    href: "/platform/alpha-intelligence/scenarios",
    label: "AlphaScenario™",
    description: "Counterfactual stress tests against the current paper book.",
  },
  {
    href: "/platform/alpha-intelligence/memory",
    label: "AlphaMemory™",
    description: "Institutional decision memory and human-reviewed lesson proposals.",
  },
  {
    href: "/platform/alpha-intelligence/replay",
    label: "AlphaReplay™",
    description: "Bitemporal \"as known at\" reconstruction of what the layer itself knew.",
  },
];

export function AlphaOverview() {
  const { token } = useAuth();
  const [brief, setBrief] = useState<IntelligenceBrief | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    apiGet<IntelligenceBrief>("/alpha/briefs/latest", token)
      .then(setBrief)
      .catch(() => setMessage("No Overnight Intelligence Brief has been generated yet — one is produced at the end of each full research cycle."));
  }, [token]);

  return (
    <div className="space-y-4">
      <h1 className="panel-title">Alpha Intelligence Layer — Overview</h1>
      <p className="text-[11px] text-terminal-muted">
        Six components sitting between the Natural Gas Digital Twin and the Specialized AI
        Agents, each turning raw data into traceable evidence: what changed, why it matters,
        whether the agents agree, what a counterfactual would show, and what history says.
      </p>

      <div className="panel">
        <div className="panel-title">Overnight Intelligence Brief</div>
        {message && !brief && <p className="text-xs text-terminal-muted">{message}</p>}
        {brief && (
          <div className="space-y-2">
            <div className="text-xs">{brief.headline}</div>
            <div className="text-[11px] text-terminal-muted">{brief.summary}</div>
            <div className="text-[10px] text-terminal-muted">
              Period {new Date(brief.period_start).toLocaleString()} – {new Date(brief.period_end).toLocaleString()}
              {" · "}generated {new Date(brief.generated_at).toLocaleString()}
            </div>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {COMPONENTS.map((c) => (
          <Link
            key={c.href}
            href={c.href}
            className="panel block hover:border-terminal-accent transition-colors"
          >
            <div className="panel-title">{c.label}</div>
            <div className="text-[11px] text-terminal-muted">{c.description}</div>
          </Link>
        ))}
      </div>
    </div>
  );
}
