"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface AgentDetail {
  agent_type: string;
  team: string;
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
  confidence_threshold: number | null;
  alert_threshold: number | null;
  escalation_threshold: number | null;
  recent_executions: { execution_id: string; status: string; last_execution_time: string; confidence: number | null }[];
  recent_errors: { execution_id: string; occurred_at: string; errors: { code: string; message: string }[] }[];
}

interface AgentVersion {
  id: string;
  agent_type: string;
  version: string;
  model_provider: string | null;
  model_name: string | null;
  system_instructions: string | null;
  status: string;
  created_by: string | null;
  created_at: string;
  evaluation_results: Record<string, unknown> | null;
  approved_by: string | null;
  approved_at: string | null;
  deployment_timestamp: string | null;
  notes: string | null;
}

const LEGAL_NEXT: Record<string, string[]> = {
  DRAFT: ["TESTING", "RETIRED"],
  TESTING: ["APPROVED", "DRAFT", "RETIRED"],
  APPROVED: ["PRODUCTION", "RETIRED"],
  PRODUCTION: ["RETIRED", "ROLLED_BACK"],
  RETIRED: [],
  ROLLED_BACK: [],
};

const NEW_VERSION_DEFAULTS = { version: "", model_name: "", system_instructions: "", notes: "" };
const OPTIMIZATION_DEFAULTS = { version: "", problem_identification: "", proposed_change: "", system_instructions: "" };

export default function AgentDetailPage() {
  const params = useParams<{ agentType: string }>();
  const agentType = params.agentType;
  const { token } = useAuth();
  const [agent, setAgent] = useState<AgentDetail | null>(null);
  const [versions, setVersions] = useState<AgentVersion[] | null>(null);
  const [newVersion, setNewVersion] = useState(NEW_VERSION_DEFAULTS);
  const [optimization, setOptimization] = useState(OPTIMIZATION_DEFAULTS);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function refresh() {
    if (!token) return;
    const [detail, versionList] = await Promise.all([
      apiGet<AgentDetail>(`/admin/agents/${agentType}`, token),
      apiGet<AgentVersion[]>(`/admin/agents/${agentType}/versions`, token),
    ]);
    setAgent(detail);
    setVersions(versionList);
  }

  useEffect(() => {
    refresh().catch(() => setMessage("Unable to load agent."));
  }, [token, agentType]);

  async function createDraft(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    setBusy("create");
    setMessage(null);
    try {
      await apiPost(`/admin/agents/${agentType}/versions`, newVersion, token);
      setNewVersion(NEW_VERSION_DEFAULTS);
      await refresh();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Could not create draft version.");
    } finally {
      setBusy(null);
    }
  }

  async function transition(versionId: string, status: string) {
    if (!token) return;
    setBusy(versionId);
    setMessage(null);
    try {
      await apiPost(`/admin/agents/${agentType}/versions/${versionId}/transition`, { status }, token);
      await refresh();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Transition failed.");
    } finally {
      setBusy(null);
    }
  }

  async function proposeOptimization(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    setBusy("optimize");
    setMessage(null);
    try {
      await apiPost(`/admin/agents/${agentType}/optimization/propose`, optimization, token);
      setOptimization(OPTIMIZATION_DEFAULTS);
      await refresh();
    } catch (err) {
      setMessage(
        err instanceof Error && err.message.includes("403")
          ? "Proposing an optimization requires a SUPER_ADMIN account."
          : "Could not submit optimization proposal."
      );
    } finally {
      setBusy(null);
    }
  }

  if (!agent || !versions) return <p className="text-xs text-terminal-muted">Loading…</p>;

  const inputClass = "w-full bg-terminal-bg border border-terminal-border rounded px-2 py-1 text-xs";

  return (
    <div className="space-y-6">
      <h1 className="panel-title">{agentType}</h1>
      {message && <p className="text-xs text-terminal-warn">{message}</p>}

      <div className="panel grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
        <div>
          <div className="text-terminal-muted">Purpose</div>
          <div>{agent.purpose}</div>
        </div>
        <div>
          <div className="text-terminal-muted">Model</div>
          <div>{agent.model ?? "—"}</div>
        </div>
        <div>
          <div className="text-terminal-muted">Total Executions</div>
          <div>{agent.total_executions}</div>
        </div>
        <div>
          <div className="text-terminal-muted">Success Rate</div>
          <div>{agent.success_rate != null ? `${(agent.success_rate * 100).toFixed(0)}%` : "—"}</div>
        </div>
      </div>

      <div>
        <div className="text-terminal-muted text-xs mb-1">Recent Errors</div>
        <div className="panel overflow-x-auto">
          <table className="mono-table w-full text-xs">
            <thead>
              <tr>
                <th>Time</th>
                <th>Errors</th>
              </tr>
            </thead>
            <tbody>
              {agent.recent_errors.length === 0 && (
                <tr>
                  <td colSpan={2} className="text-terminal-muted">
                    No recent errors.
                  </td>
                </tr>
              )}
              {agent.recent_errors.map((e) => (
                <tr key={e.execution_id}>
                  <td className="whitespace-nowrap">{new Date(e.occurred_at).toLocaleString()}</td>
                  <td>{e.errors.map((err) => `${err.code}: ${err.message}`).join("; ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <h2 className="panel-title mb-2">Versions</h2>
        <div className="panel overflow-x-auto">
          <table className="mono-table w-full text-xs">
            <thead>
              <tr>
                <th>Version</th>
                <th>Model</th>
                <th>Status</th>
                <th>Created</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {versions.map((v) => (
                <tr key={v.id}>
                  <td>{v.version}</td>
                  <td>{v.model_name ?? "—"}</td>
                  <td>{v.status}</td>
                  <td className="whitespace-nowrap">{new Date(v.created_at).toLocaleString()}</td>
                  <td className="flex flex-wrap gap-1">
                    {(LEGAL_NEXT[v.status] ?? []).map((next) => (
                      <button
                        key={next}
                        disabled={busy === v.id}
                        onClick={() => transition(v.id, next)}
                        className="text-[10px] px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-accent disabled:opacity-50"
                      >
                        {next}
                      </button>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <h2 className="panel-title mb-2">Create Draft Version</h2>
        <form onSubmit={createDraft} className="panel grid grid-cols-2 gap-2">
          <input
            required
            placeholder="Version (e.g. 0.2.0-draft1)"
            className={inputClass}
            value={newVersion.version}
            onChange={(e) => setNewVersion((f) => ({ ...f, version: e.target.value }))}
          />
          <input
            placeholder="Model name (must be an APPROVED model to reach production)"
            className={inputClass}
            value={newVersion.model_name}
            onChange={(e) => setNewVersion((f) => ({ ...f, model_name: e.target.value }))}
          />
          <textarea
            placeholder="System instructions"
            className={`${inputClass} col-span-2`}
            rows={3}
            value={newVersion.system_instructions}
            onChange={(e) => setNewVersion((f) => ({ ...f, system_instructions: e.target.value }))}
          />
          <textarea
            placeholder="Notes"
            className={`${inputClass} col-span-2`}
            rows={2}
            value={newVersion.notes}
            onChange={(e) => setNewVersion((f) => ({ ...f, notes: e.target.value }))}
          />
          <button
            type="submit"
            disabled={busy === "create"}
            className="text-xs px-3 py-1 border border-terminal-accent text-terminal-accent rounded hover:bg-terminal-accent/10 disabled:opacity-50 col-span-2 w-fit"
          >
            Create Draft
          </button>
        </form>
      </div>

      <div>
        <h2 className="panel-title mb-2">Propose Optimization (SUPER_ADMIN)</h2>
        <p className="text-[11px] text-terminal-muted mb-2">
          Records a real performance-review snapshot alongside your stated problem/proposed change,
          then creates a draft version through the same review lifecycle above — no
          optimization-specific fast path to production.
        </p>
        <form onSubmit={proposeOptimization} className="panel grid grid-cols-2 gap-2">
          <input
            required
            placeholder="Version"
            className={inputClass}
            value={optimization.version}
            onChange={(e) => setOptimization((f) => ({ ...f, version: e.target.value }))}
          />
          <input
            placeholder="System instructions (optional)"
            className={inputClass}
            value={optimization.system_instructions}
            onChange={(e) => setOptimization((f) => ({ ...f, system_instructions: e.target.value }))}
          />
          <textarea
            required
            placeholder="Problem identification"
            className={`${inputClass} col-span-2`}
            rows={2}
            value={optimization.problem_identification}
            onChange={(e) => setOptimization((f) => ({ ...f, problem_identification: e.target.value }))}
          />
          <textarea
            required
            placeholder="Proposed change"
            className={`${inputClass} col-span-2`}
            rows={2}
            value={optimization.proposed_change}
            onChange={(e) => setOptimization((f) => ({ ...f, proposed_change: e.target.value }))}
          />
          <button
            type="submit"
            disabled={busy === "optimize"}
            className="text-xs px-3 py-1 border border-terminal-accent text-terminal-accent rounded hover:bg-terminal-accent/10 disabled:opacity-50 col-span-2 w-fit"
          >
            Submit Proposal
          </button>
        </form>
      </div>
    </div>
  );
}
