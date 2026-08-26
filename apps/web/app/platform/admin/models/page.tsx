"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPatch, apiPost } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface ModelDefinition {
  id: string;
  provider: string;
  model_name: string;
  version: string | null;
  purpose: string | null;
  status: string;
  context_window: number | null;
  cost_per_1k_input_tokens: number | null;
  cost_per_1k_output_tokens: number | null;
  updated_by: string | null;
  approved_at: string | null;
}

const STATUSES = ["AVAILABLE", "TESTING", "APPROVED", "DEPRECATED", "DISABLED"];

const NEW_MODEL_DEFAULTS = { provider: "", model_name: "", purpose: "" };

export default function AdminModelsPage() {
  const { token } = useAuth();
  const [models, setModels] = useState<ModelDefinition[] | null>(null);
  const [form, setForm] = useState(NEW_MODEL_DEFAULTS);
  const [reason, setReason] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  async function refresh() {
    if (!token) return;
    try {
      setModels(await apiGet<ModelDefinition[]>("/admin/models", token));
      setForbidden(false);
    } catch (err) {
      if (err instanceof Error && err.message.includes("403")) setForbidden(true);
      else setMessage("Unable to load models.");
    }
  }

  useEffect(() => {
    refresh();
  }, [token]);

  async function createModel(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    setBusy("create");
    try {
      await apiPost("/admin/models", form, token);
      setForm(NEW_MODEL_DEFAULTS);
      await refresh();
    } catch {
      setMessage("Could not create model definition.");
    } finally {
      setBusy(null);
    }
  }

  async function changeStatus(modelId: string, status: string) {
    if (!token) return;
    setBusy(modelId);
    try {
      await apiPatch(`/admin/models/${modelId}/status`, { status, reason: reason[modelId] || undefined }, token);
      await refresh();
    } catch {
      setMessage("Could not update status.");
    } finally {
      setBusy(null);
    }
  }

  if (forbidden) {
    return (
      <div className="panel max-w-md">
        <div className="panel-title">Model Management</div>
        <p className="text-xs text-terminal-muted">
          Model management is reserved for a SUPER_ADMIN account (docs/agent-governance.md §6) — a
          standard ADMIN does not have the <code>admin.model_management</code> permission.
        </p>
      </div>
    );
  }

  if (!models) return <p className="text-xs text-terminal-muted">Loading…</p>;

  const inputClass = "w-full bg-terminal-bg border border-terminal-border rounded px-2 py-1 text-xs";

  return (
    <div className="space-y-4">
      <h1 className="panel-title">Model Management</h1>
      <p className="text-[11px] text-terminal-muted">
        An agent version may only reach APPROVED/PRODUCTION if its model is itself an APPROVED
        model definition here (docs/agent-governance.md §6) — enforced server-side, not just by
        this UI.
      </p>
      {message && <p className="text-xs text-terminal-warn">{message}</p>}

      <form onSubmit={createModel} className="panel grid grid-cols-2 md:grid-cols-4 gap-2">
        <input
          required
          placeholder="Provider"
          className={inputClass}
          value={form.provider}
          onChange={(e) => setForm((f) => ({ ...f, provider: e.target.value }))}
        />
        <input
          required
          placeholder="Model name"
          className={inputClass}
          value={form.model_name}
          onChange={(e) => setForm((f) => ({ ...f, model_name: e.target.value }))}
        />
        <input
          placeholder="Purpose"
          className={inputClass}
          value={form.purpose}
          onChange={(e) => setForm((f) => ({ ...f, purpose: e.target.value }))}
        />
        <button
          type="submit"
          disabled={busy === "create"}
          className="text-xs px-3 py-1 border border-terminal-accent text-terminal-accent rounded hover:bg-terminal-accent/10 disabled:opacity-50"
        >
          Add Model
        </button>
      </form>

      <div className="panel overflow-x-auto">
        <table className="mono-table w-full">
          <thead>
            <tr>
              <th>Provider</th>
              <th>Model</th>
              <th>Purpose</th>
              <th>Status</th>
              <th>Reason for change</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {models.map((m) => (
              <tr key={m.id}>
                <td>{m.provider}</td>
                <td>{m.model_name}</td>
                <td>{m.purpose ?? "—"}</td>
                <td>{m.status}</td>
                <td>
                  <input
                    className={inputClass}
                    placeholder="optional"
                    value={reason[m.id] ?? ""}
                    onChange={(e) => setReason((r) => ({ ...r, [m.id]: e.target.value }))}
                  />
                </td>
                <td className="flex flex-wrap gap-1">
                  {STATUSES.filter((s) => s !== m.status).map((s) => (
                    <button
                      key={s}
                      disabled={busy === m.id}
                      onClick={() => changeStatus(m.id, s)}
                      className="text-[10px] px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-accent disabled:opacity-50"
                    >
                      {s}
                    </button>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
