"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPut } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface RiskLimits {
  max_position_size: number;
  max_risk_per_trade: number;
  max_daily_loss: number;
  max_drawdown: number;
  max_portfolio_var: number;
  max_sector_exposure: number;
  max_contract_exposure: number;
  max_correlated_exposure: number;
  effective_from: string;
  set_by_user_id: string | null;
}

const FIELDS: { key: keyof RiskLimits; label: string }[] = [
  { key: "max_position_size", label: "Max Position Size" },
  { key: "max_risk_per_trade", label: "Max Risk Per Trade" },
  { key: "max_daily_loss", label: "Max Daily Loss" },
  { key: "max_drawdown", label: "Max Drawdown" },
  { key: "max_portfolio_var", label: "Max Portfolio VaR" },
  { key: "max_sector_exposure", label: "Max Sector Exposure" },
  { key: "max_contract_exposure", label: "Max Contract Exposure" },
  { key: "max_correlated_exposure", label: "Max Correlated Exposure" },
];

export default function AdminRiskSettingsPage() {
  const { token } = useAuth();
  const [limits, setLimits] = useState<RiskLimits | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [forbidden, setForbidden] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    if (!token) return;
    try {
      const data = await apiGet<RiskLimits>("/admin/risk-settings", token);
      setLimits(data);
      setDraft(Object.fromEntries(FIELDS.map((f) => [f.key, String(data[f.key])])));
      setForbidden(false);
    } catch (err) {
      if (err instanceof Error && err.message.includes("403")) setForbidden(true);
      else setMessage("Unable to load risk settings.");
    }
  }

  useEffect(() => {
    refresh();
  }, [token]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    if (!reason.trim()) {
      setMessage("A reason is required for every risk-setting change.");
      return;
    }
    setBusy(true);
    setMessage(null);
    try {
      const body = Object.fromEntries(FIELDS.map((f) => [f.key, Number(draft[f.key])]));
      await apiPut("/admin/risk-settings", { ...body, reason }, token);
      setReason("");
      setMessage("Risk settings updated.");
      await refresh();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Could not update risk settings.");
    } finally {
      setBusy(false);
    }
  }

  if (forbidden) {
    return (
      <div className="panel max-w-md">
        <div className="panel-title">Risk Settings</div>
        <p className="text-xs text-terminal-muted">
          Admin-governed risk settings are reserved for a SUPER_ADMIN account
          (docs/agent-governance.md §6) — a standard ADMIN does not have the{" "}
          <code>admin.risk_settings</code> permission. Day-to-day limit changes remain available to
          a RISK_MANAGER via the trading dashboard.
        </p>
      </div>
    );
  }

  if (!limits) return <p className="text-xs text-terminal-muted">Loading…</p>;

  const inputClass = "w-full bg-terminal-bg border border-terminal-border rounded px-2 py-1 text-xs";

  return (
    <div className="space-y-4">
      <h1 className="panel-title">Risk Settings</h1>
      <p className="text-[11px] text-terminal-muted">
        Every change here requires a reason and is recorded as an audit event with the previous and
        new value together (spec §44).
      </p>
      {message && <p className="text-xs text-terminal-warn">{message}</p>}

      <form onSubmit={save} className="panel space-y-3">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {FIELDS.map((f) => (
            <label key={f.key} className="flex flex-col gap-1 text-xs">
              {f.label}
              <input
                className={inputClass}
                value={draft[f.key] ?? ""}
                onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))}
              />
            </label>
          ))}
        </div>
        <label className="flex flex-col gap-1 text-xs">
          Reason (required)
          <textarea
            required
            className={inputClass}
            rows={2}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
        <button
          type="submit"
          disabled={busy}
          className="text-xs px-3 py-1 border border-terminal-accent text-terminal-accent rounded hover:bg-terminal-accent/10 disabled:opacity-50"
        >
          Save
        </button>
        <div className="text-[10px] text-terminal-muted">
          Last set by {limits.set_by_user_id ?? "system"} · effective from{" "}
          {new Date(limits.effective_from).toLocaleString()}
        </div>
      </form>
    </div>
  );
}
