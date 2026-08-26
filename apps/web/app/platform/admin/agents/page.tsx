"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { apiGet, apiPatch, apiPost } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface AgentView {
  agent_type: string;
  team: string;
  business_functions: string[];
  purpose: string;
  implemented: boolean;
  administrable: boolean;
  agent_id: string | null;
  version: string | null;
  model_provider: string | null;
  model: string | null;
  total_executions: number;
  last_execution_time: string | null;
  last_status: string | null;
  average_latency_ms: number | null;
  success_rate: number | null;
  error_rate: number | null;
  status: string | null;
  notes: string | null;
}

const TEAM_ORDER = [
  "EXECUTIVE",
  "FUNDAMENTAL_RESEARCH",
  "MARKET_INTELLIGENCE",
  "QUANTITATIVE",
  "STRATEGY",
  "INVESTMENT_COMMITTEE",
  "INDEPENDENT_RISK",
];

const TEAM_LABEL: Record<string, string> = {
  EXECUTIVE: "Leadership",
  FUNDAMENTAL_RESEARCH: "Fundamental Research",
  MARKET_INTELLIGENCE: "Market Intelligence",
  QUANTITATIVE: "Quantitative Research",
  STRATEGY: "Strategy",
  INVESTMENT_COMMITTEE: "Investment Committee",
  INDEPENDENT_RISK: "Risk",
};

export default function AdminAgentsPage() {
  const { token } = useAuth();
  const [agents, setAgents] = useState<AgentView[] | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function refresh() {
    if (!token) return;
    setAgents(await apiGet<AgentView[]>("/admin/agents", token));
  }

  useEffect(() => {
    refresh().catch(() => setMessage("Unable to load agents."));
  }, [token]);

  async function toggleStatus(agentType: string, newStatus: string) {
    if (!token) return;
    setBusy(agentType);
    try {
      await apiPatch(`/admin/agents/${agentType}`, { status: newStatus }, token);
      await refresh();
    } catch {
      setMessage(`Could not update ${agentType}.`);
    } finally {
      setBusy(null);
    }
  }

  async function runChiefTradingAgent() {
    if (!token) return;
    setBusy("CHIEF_TRADING_AGENT");
    setMessage(null);
    try {
      const result = await apiPost<{ trade_ideas_generated: number }>(
        "/admin/agents/CHIEF_TRADING_AGENT/run",
        undefined,
        token
      );
      setMessage(`Run complete — ${result.trade_ideas_generated} trade idea(s) generated.`);
      await refresh();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Run failed.");
    } finally {
      setBusy(null);
    }
  }

  if (message && !agents) return <p className="text-xs text-terminal-bear">{message}</p>;
  if (!agents) return <p className="text-xs text-terminal-muted">Loading…</p>;

  const byTeam = new Map<string, AgentView[]>();
  for (const agent of agents) {
    if (!byTeam.has(agent.team)) byTeam.set(agent.team, []);
    byTeam.get(agent.team)!.push(agent);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="panel-title">AI Agent Control Center</h1>
        <button
          onClick={runChiefTradingAgent}
          disabled={busy !== null}
          className="text-xs px-3 py-1 border border-terminal-accent text-terminal-accent rounded hover:bg-terminal-accent/10 disabled:opacity-50"
        >
          Run Chief Trading Agent
        </button>
      </div>
      {message && <p className="text-xs text-terminal-warn">{message}</p>}
      <p className="text-[11px] text-terminal-muted">
        Only the Chief Trading Agent is independently runnable — every other implemented seat
        executes as part of its composed research cycle (docs/agent-governance.md §3).
      </p>

      {TEAM_ORDER.filter((t) => byTeam.has(t)).map((team) => (
        <div key={team}>
          <h2 className="text-xs uppercase tracking-wide text-terminal-muted mb-1">{TEAM_LABEL[team] ?? team}</h2>
          <div className="panel overflow-x-auto">
            <table className="mono-table w-full">
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>Implemented</th>
                  <th>Status</th>
                  <th>Model</th>
                  <th>Executions</th>
                  <th>Success Rate</th>
                  <th>Last Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {byTeam.get(team)!.map((a) => (
                  <tr key={a.agent_type}>
                    <td className="whitespace-nowrap">{a.agent_type}</td>
                    <td>{a.implemented ? "Yes" : "No"}</td>
                    <td>
                      {a.administrable ? (
                        <select
                          value={a.status ?? ""}
                          disabled={busy === a.agent_type}
                          onChange={(e) => toggleStatus(a.agent_type, e.target.value)}
                          className="bg-terminal-bg border border-terminal-border rounded px-1 py-0.5 text-xs"
                        >
                          {["ACTIVE", "PAUSED", "DISABLED", "TESTING"].map((s) => (
                            <option key={s} value={s}>
                              {s}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <span className="text-terminal-muted">{a.status ?? "—"}</span>
                      )}
                    </td>
                    <td>{a.model ?? "—"}</td>
                    <td>{a.total_executions}</td>
                    <td>{a.success_rate != null ? `${(a.success_rate * 100).toFixed(0)}%` : "—"}</td>
                    <td>{a.last_status ?? "Never run"}</td>
                    <td>
                      {a.implemented && (
                        <Link
                          href={`/platform/admin/agents/${a.agent_type}`}
                          className="text-[10px] px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-accent"
                        >
                          Details
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  );
}
