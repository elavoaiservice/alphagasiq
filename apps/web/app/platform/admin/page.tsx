"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface Overview {
  active_users: number;
  invited_users: number;
  suspended_users: number;
  active_organizations: number;
  users_logged_in_today: number;
  chief_trading_agent_queries: number;
  paper_trading_activity: { open_positions: number; total_fills: number };
  agent_execution_health: { total_executions_logged: number };
  data_feed_health: { total_feeds: number; healthy: number; degraded_or_unavailable: number; not_configured: number };
  stale_data_feeds: number;
  not_yet_available: string[];
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="border border-terminal-border rounded p-3">
      <div className="text-[10px] uppercase tracking-wide text-terminal-muted">{label}</div>
      <div className="text-xl mt-1">{value}</div>
    </div>
  );
}

export default function AdminOverviewPage() {
  const { token } = useAuth();
  const [overview, setOverview] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    apiGet<Overview>("/admin/overview", token)
      .then(setOverview)
      .catch(() => setError("Unable to load overview metrics."));
  }, [token]);

  if (error) return <p className="text-xs text-terminal-bear">{error}</p>;
  if (!overview) return <p className="text-xs text-terminal-muted">Loading…</p>;

  return (
    <div className="space-y-4">
      <h1 className="panel-title">Overview</h1>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Active Users" value={overview.active_users} />
        <Stat label="Invited Users" value={overview.invited_users} />
        <Stat label="Suspended Users" value={overview.suspended_users} />
        <Stat label="Active Organizations" value={overview.active_organizations} />
        <Stat label="Logged In Today" value={overview.users_logged_in_today} />
        <Stat label="Chief Trading Agent Queries" value={overview.chief_trading_agent_queries} />
        <Stat label="Open Paper Positions" value={overview.paper_trading_activity.open_positions} />
        <Stat label="Paper Fills" value={overview.paper_trading_activity.total_fills} />
        <Stat label="Healthy Data Feeds" value={`${overview.data_feed_health.healthy}/${overview.data_feed_health.total_feeds}`} />
        <Stat label="Stale Data Feeds" value={overview.stale_data_feeds} />
      </div>
      {overview.not_yet_available.length > 0 && (
        <div className="text-[11px] text-terminal-muted border-t border-terminal-border pt-2">
          Not yet available: {overview.not_yet_available.join(", ")} — these require live
          health-monitoring infrastructure beyond this platform&apos;s current scope.
        </div>
      )}
    </div>
  );
}
