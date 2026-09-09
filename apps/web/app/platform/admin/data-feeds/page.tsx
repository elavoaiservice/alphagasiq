"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPatch, apiPost } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface DataFeed {
  provider_id: string;
  source_type: string | null;
  license_type: string | null;
  public_or_commercial: string | null;
  redistribution_allowed: boolean | null;
  ai_processing_allowed: boolean | null;
  environment: string | null;
  connection_status: string;
  detail: string;
  last_checked_at: string | null;
  last_successful_ingestion_at: string | null;
  freshness_seconds: number | null;
  freshness_sla_seconds: number | null;
  freshness_status: "LIVE" | "CURRENT" | "DELAYED" | "STALE" | "FAILED" | "UNKNOWN";
  data_quality_score: number | null;
  enabled: boolean;
  paused: boolean;
  polling_frequency_seconds: number | null;
  effective_poll_seconds: number | null;
  last_polled_at: string | null;
  next_poll_due_at: string | null;
  poll_advisory: string | null;
  freshness_threshold_seconds: number | null;
  priority: number;
  fallback_provider_id: string | null;
  notes: string | null;
  updated_by: string | null;
  updated_at: string | null;
  affected_agents: string[];
  affected_business_functions: string[];
  dependency_chain: string[];
}

interface DataFeedEvent {
  id: string;
  event_type: string;
  status: string;
  detail: string;
  records_received: number | null;
  latency_ms: number | null;
  occurred_at: string;
}

const STATUS_COLOR: Record<string, string> = {
  healthy: "text-terminal-bull",
  degraded: "text-terminal-warn",
  unavailable: "text-terminal-bear",
  not_configured: "text-terminal-muted",
  unknown: "text-terminal-muted",
};

const FRESHNESS_COLOR: Record<string, string> = {
  LIVE: "text-terminal-bull",
  CURRENT: "text-terminal-bull",
  DELAYED: "text-terminal-warn",
  STALE: "text-terminal-warn",
  FAILED: "text-terminal-bear",
  UNKNOWN: "text-terminal-muted",
};

function EditForm({ feed, token, onSaved }: { feed: DataFeed; token: string; onSaved: () => void }) {
  const [draft, setDraft] = useState({
    enabled: feed.enabled,
    paused: feed.paused,
    polling_frequency_seconds: feed.polling_frequency_seconds ?? "",
    freshness_threshold_seconds: feed.freshness_threshold_seconds ?? "",
    priority: feed.priority,
    fallback_provider_id: feed.fallback_provider_id ?? "",
    notes: feed.notes ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      await apiPatch(`/admin/data-feeds/${feed.provider_id}`, {
        enabled: draft.enabled,
        paused: draft.paused,
        polling_frequency_seconds: draft.polling_frequency_seconds === "" ? null : Number(draft.polling_frequency_seconds),
        freshness_threshold_seconds: draft.freshness_threshold_seconds === "" ? null : Number(draft.freshness_threshold_seconds),
        priority: Number(draft.priority),
        fallback_provider_id: draft.fallback_provider_id || null,
        notes: draft.notes || null,
      }, token);
      onSaved();
    } catch {
      setMessage("Could not save changes.");
    } finally {
      setBusy(false);
    }
  }

  const inputClass = "w-full bg-terminal-bg border border-terminal-border rounded px-2 py-1 text-xs";

  return (
    <div className="grid grid-cols-2 gap-3 text-xs">
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft((d) => ({ ...d, enabled: e.target.checked }))} />
        Enabled
      </label>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={draft.paused} onChange={(e) => setDraft((d) => ({ ...d, paused: e.target.checked }))} />
        Paused
      </label>
      <label className="flex flex-col gap-1">
        Polling frequency (seconds)
        <input className={inputClass} value={draft.polling_frequency_seconds} onChange={(e) => setDraft((d) => ({ ...d, polling_frequency_seconds: e.target.value }))} />
        <span className="text-[10px] text-terminal-muted">
          {feed.effective_poll_seconds === null
            ? "Not scheduled — this feed is a stub with nothing to fetch."
            : feed.polling_frequency_seconds === null
              ? `Blank = this feed's default, ${feed.effective_poll_seconds}s.`
              : `In force: every ${feed.effective_poll_seconds}s.`}
        </span>
      </label>
      <label className="flex flex-col gap-1">
        Freshness threshold (seconds)
        <input className={inputClass} value={draft.freshness_threshold_seconds} onChange={(e) => setDraft((d) => ({ ...d, freshness_threshold_seconds: e.target.value }))} />
      </label>
      <label className="flex flex-col gap-1">
        Priority
        <input className={inputClass} value={draft.priority} onChange={(e) => setDraft((d) => ({ ...d, priority: e.target.value as unknown as number }))} />
      </label>
      <label className="flex flex-col gap-1">
        Fallback provider
        <input className={inputClass} value={draft.fallback_provider_id} onChange={(e) => setDraft((d) => ({ ...d, fallback_provider_id: e.target.value }))} />
      </label>
      <label className="flex flex-col gap-1 col-span-2">
        Notes
        <textarea className={inputClass} rows={2} value={draft.notes} onChange={(e) => setDraft((d) => ({ ...d, notes: e.target.value }))} />
      </label>
      <div className="col-span-2 flex items-center gap-2">
        <button
          onClick={save}
          disabled={busy}
          className="text-xs px-3 py-1 border border-terminal-accent text-terminal-accent rounded hover:bg-terminal-accent/10 disabled:opacity-50"
        >
          Save
        </button>
        {message && <span className="text-terminal-warn">{message}</span>}
      </div>
    </div>
  );
}

function FeedDetail({ feed, token, onChanged }: { feed: DataFeed; token: string; onChanged: () => void }) {
  const [events, setEvents] = useState<DataFeedEvent[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function loadEvents() {
    setEvents(await apiGet<DataFeedEvent[]>(`/admin/data-feeds/${feed.provider_id}/events`, token));
  }

  useEffect(() => {
    loadEvents().catch(() => setMessage("Unable to load ingestion log."));
  }, [feed.provider_id, token]);

  async function testConnection() {
    setBusy("test");
    setMessage(null);
    try {
      await apiPost(`/admin/data-feeds/${feed.provider_id}/test-connection`, undefined, token);
      await loadEvents();
      onChanged();
    } catch {
      setMessage("Test connection failed to record.");
    } finally {
      setBusy(null);
    }
  }

  async function refresh() {
    setBusy("refresh");
    setMessage(null);
    try {
      await apiPost(`/admin/data-feeds/${feed.provider_id}/refresh`, undefined, token);
      await loadEvents();
      onChanged();
    } catch {
      setMessage("Manual refresh failed to record.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="panel space-y-4">
      <div className="flex items-center justify-between">
        <div className="panel-title">{feed.provider_id}</div>
        <div className="flex gap-2">
          <button
            onClick={testConnection}
            disabled={busy !== null}
            className="text-[10px] px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-accent disabled:opacity-50"
          >
            Test Connection
          </button>
          <button
            onClick={refresh}
            disabled={busy !== null}
            className="text-[10px] px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-accent disabled:opacity-50"
          >
            Trigger Manual Refresh
          </button>
        </div>
      </div>
      {message && <p className="text-xs text-terminal-warn">{message}</p>}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
        <div>
          <div className="text-terminal-muted">Connection Status</div>
          <div className={STATUS_COLOR[feed.connection_status] ?? ""}>{feed.connection_status}</div>
        </div>
        <div>
          <div className="text-terminal-muted">Source Type</div>
          <div>{feed.source_type ?? "—"}</div>
        </div>
        <div>
          <div className="text-terminal-muted">Freshness</div>
          <div className={FRESHNESS_COLOR[feed.freshness_status] ?? ""}>{feed.freshness_status}</div>
        </div>
        <div>
          <div className="text-terminal-muted">Data Quality Score</div>
          <div>{feed.data_quality_score != null ? feed.data_quality_score.toFixed(0) : "not yet available"}</div>
        </div>
        <div>
          <div className="text-terminal-muted">Last Successful Ingestion</div>
          <div>
            {feed.last_successful_ingestion_at ? new Date(feed.last_successful_ingestion_at).toLocaleString() : "never"}
          </div>
        </div>
        <div>
          <div className="text-terminal-muted">Polling</div>
          <div>
            {feed.effective_poll_seconds === null ? (
              <span className="text-terminal-muted">not scheduled</span>
            ) : !feed.enabled ? (
              <span className="text-terminal-muted">disabled</span>
            ) : feed.paused ? (
              <span className="text-terminal-warn">paused</span>
            ) : (
              <>every {feed.effective_poll_seconds}s</>
            )}
          </div>
        </div>
        <div>
          <div className="text-terminal-muted">Last Polled</div>
          <div>{feed.last_polled_at ? new Date(feed.last_polled_at).toLocaleString() : "never"}</div>
        </div>
        <div>
          <div className="text-terminal-muted">Next Poll Due</div>
          <div>
            {feed.effective_poll_seconds === null || !feed.enabled || feed.paused
              ? "—"
              : feed.next_poll_due_at
                ? new Date(feed.next_poll_due_at).toLocaleString()
                : "now"}
          </div>
        </div>
      </div>

      {feed.poll_advisory && (
        <div className="rounded border border-terminal-warn/40 bg-terminal-warn/10 p-2 text-[11px] text-terminal-warn">
          {feed.poll_advisory} The setting is still honoured — this is advice, not a limit.
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
        <div>
          <div className="text-terminal-muted">License Type</div>
          <div>{feed.license_type ?? "unknown"}</div>
        </div>
        <div>
          <div className="text-terminal-muted">Public / Commercial</div>
          <div>{feed.public_or_commercial ?? "unknown"}</div>
        </div>
        <div>
          <div className="text-terminal-muted">Redistribution Allowed</div>
          <div>{feed.redistribution_allowed === null ? "unknown" : feed.redistribution_allowed ? "Yes" : "No"}</div>
        </div>
        <div>
          <div className="text-terminal-muted">AI Processing Allowed</div>
          <div>{feed.ai_processing_allowed === null ? "unknown" : feed.ai_processing_allowed ? "Yes" : "No"}</div>
        </div>
      </div>

      <div className="text-xs">
        <div className="text-terminal-muted mb-1">Dependency Chain</div>
        <div>{feed.dependency_chain.length ? feed.dependency_chain.join(" → ") : "—"}</div>
      </div>
      <div className="grid grid-cols-2 gap-3 text-xs">
        <div>
          <div className="text-terminal-muted mb-1">Affected Agents</div>
          <div>{feed.affected_agents.join(", ") || "—"}</div>
        </div>
        <div>
          <div className="text-terminal-muted mb-1">Affected Business Functions</div>
          <div>{feed.affected_business_functions.join(", ") || "—"}</div>
        </div>
      </div>

      <EditForm feed={feed} token={token} onSaved={onChanged} />

      <div>
        <div className="text-terminal-muted text-xs mb-1">Ingestion Log</div>
        <div className="overflow-x-auto">
          <table className="mono-table w-full text-xs">
            <thead>
              <tr>
                <th>Time</th>
                <th>Event</th>
                <th>Status</th>
                <th>Detail</th>
                <th>Records</th>
                <th>Latency</th>
              </tr>
            </thead>
            <tbody>
              {(events ?? []).map((e) => (
                <tr key={e.id}>
                  <td className="whitespace-nowrap">{new Date(e.occurred_at).toLocaleString()}</td>
                  <td>{e.event_type}</td>
                  <td className={e.status === "error" ? "text-terminal-bear" : "text-terminal-bull"}>{e.status}</td>
                  <td>{e.detail}</td>
                  <td>{e.records_received ?? "—"}</td>
                  <td>{e.latency_ms != null ? `${e.latency_ms.toFixed(0)}ms` : "—"}</td>
                </tr>
              ))}
              {events?.length === 0 && (
                <tr>
                  <td colSpan={6} className="text-terminal-muted">
                    No events recorded yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export default function AdminDataFeedsPage() {
  const { token } = useAuth();
  const [feeds, setFeeds] = useState<DataFeed[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function refresh() {
    if (!token) return;
    setFeeds(await apiGet<DataFeed[]>("/admin/data-feeds", token));
  }

  useEffect(() => {
    refresh().catch(() => setMessage("Unable to load data feeds."));
  }, [token]);

  if (message) return <p className="text-xs text-terminal-bear">{message}</p>;
  if (!feeds) return <p className="text-xs text-terminal-muted">Loading…</p>;

  const activeFeed = feeds.find((f) => f.provider_id === selected) ?? null;

  return (
    <div className="space-y-4">
      <h1 className="panel-title">Data Feeds</h1>
      <p className="text-[11px] text-terminal-muted">
        Every feed&apos;s API key is environment-provisioned only — there is no credential field
        here to view or edit (docs/access-model.md).
      </p>
      <div className="panel overflow-x-auto">
        <table className="mono-table w-full">
          <thead>
            <tr>
              <th>Provider</th>
              <th>Status</th>
              <th>Enabled</th>
              <th>Paused</th>
              <th>Priority</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {feeds.map((f) => (
              <tr key={f.provider_id}>
                <td className="whitespace-nowrap">{f.provider_id}</td>
                <td className={STATUS_COLOR[f.connection_status] ?? ""}>{f.connection_status}</td>
                <td>{f.enabled ? "Yes" : "No"}</td>
                <td>{f.paused ? "Yes" : "No"}</td>
                <td>{f.priority}</td>
                <td>
                  <button
                    onClick={() => setSelected(f.provider_id === selected ? null : f.provider_id)}
                    className="text-[10px] px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-accent"
                  >
                    {f.provider_id === selected ? "Close" : "Manage"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {activeFeed && <FeedDetail feed={activeFeed} token={token!} onChanged={refresh} />}
    </div>
  );
}
