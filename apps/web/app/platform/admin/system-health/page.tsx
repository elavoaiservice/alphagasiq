"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface SystemHealth {
  data_feeds: { total: number; healthy: number; not_configured: number };
  agents: { total_administrable: number; active: number; paused_or_disabled: number };
  models: { total: number; approved: number };
  risk_governor: { status: string; version: string; trading_halted: boolean };
  event_bus: { implementation: string };
  database: { status: string };
  checked_at: string;
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="border border-terminal-border rounded p-3">
      <div className="text-[10px] uppercase tracking-wide text-terminal-muted">{label}</div>
      <div className="text-xl mt-1">{value}</div>
    </div>
  );
}

export default function AdminSystemHealthPage() {
  const { token } = useAuth();
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    apiGet<SystemHealth>("/admin/system-health", token)
      .then(setHealth)
      .catch(() => setMessage("Unable to load system health."));
  }, [token]);

  if (message) return <p className="text-xs text-terminal-bear">{message}</p>;
  if (!health) return <p className="text-xs text-terminal-muted">Loading…</p>;

  return (
    <div className="space-y-4">
      <h1 className="panel-title">System Health</h1>
      <p className="text-[11px] text-terminal-muted">
        Live rollup as of {new Date(health.checked_at).toLocaleString()} — computed from real
        platform state, not fabricated (docs/agent-governance.md §8).
      </p>

      <div>
        <h2 className="text-xs uppercase tracking-wide text-terminal-muted mb-1">Data Feeds</h2>
        <div className="grid grid-cols-3 gap-3">
          <Stat label="Total" value={health.data_feeds.total} />
          <Stat label="Healthy" value={health.data_feeds.healthy} />
          <Stat label="Not Configured" value={health.data_feeds.not_configured} />
        </div>
      </div>

      <div>
        <h2 className="text-xs uppercase tracking-wide text-terminal-muted mb-1">Agents</h2>
        <div className="grid grid-cols-3 gap-3">
          <Stat label="Administrable" value={health.agents.total_administrable} />
          <Stat label="Active" value={health.agents.active} />
          <Stat label="Paused/Disabled" value={health.agents.paused_or_disabled} />
        </div>
      </div>

      <div>
        <h2 className="text-xs uppercase tracking-wide text-terminal-muted mb-1">Models</h2>
        <div className="grid grid-cols-2 gap-3">
          <Stat label="Total" value={health.models.total} />
          <Stat label="Approved" value={health.models.approved} />
        </div>
      </div>

      <div>
        <h2 className="text-xs uppercase tracking-wide text-terminal-muted mb-1">Risk Governor</h2>
        <div className="grid grid-cols-3 gap-3">
          <Stat label="Status" value={health.risk_governor.status} />
          <Stat label="Version" value={health.risk_governor.version} />
          <Stat
            label="Trading Halted"
            value={
              <span className={health.risk_governor.trading_halted ? "text-terminal-bear" : "text-terminal-bull"}>
                {health.risk_governor.trading_halted ? "Yes" : "No"}
              </span>
            }
          />
        </div>
      </div>

      <div>
        <h2 className="text-xs uppercase tracking-wide text-terminal-muted mb-1">Infrastructure</h2>
        <div className="grid grid-cols-2 gap-3">
          <Stat label="Event Bus" value={health.event_bus.implementation} />
          <Stat label="Database" value={health.database.status} />
        </div>
      </div>
    </div>
  );
}
