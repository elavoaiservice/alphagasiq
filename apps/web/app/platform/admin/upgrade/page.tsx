"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface Status { configured: boolean; running: boolean; log: string }

export default function UpgradePage() {
  const { token } = useAuth();
  const [status, setStatus] = useState<Status | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [starting, setStarting] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const logRef = useRef<HTMLPreElement | null>(null);

  const poll = useCallback(async () => {
    if (!token) return;
    try {
      const s = await apiGet<Status>("/admin/upgrade/status", token);
      setStatus(s);
    } catch {
      setForbidden(true);
    }
  }, [token]);

  useEffect(() => {
    poll();
    const id = setInterval(poll, 2500);
    return () => clearInterval(id);
  }, [poll]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [status?.log]);

  async function upgrade() {
    if (!token) return;
    if (!confirm("Pull the latest code, rebuild, and restart the platform? The app may be briefly unavailable during restart.")) return;
    setStarting(true); setMsg(null);
    try {
      const r = await apiPost<{ ok: boolean; error?: string }>("/admin/upgrade", undefined, token);
      setMsg(r.ok ? "Upgrade started — watch the log below." : (r.error ?? "Could not start."));
      poll();
    } catch {
      setMsg("Failed to start upgrade.");
    } finally { setStarting(false); }
  }

  if (forbidden) {
    return (
      <div className="panel max-w-md">
        <div className="panel-title">Upgrade</div>
        <p className="text-xs text-terminal-muted">
          Upgrades are reserved for a SUPER_ADMIN account (<code>admin.system_settings</code>).
        </p>
      </div>
    );
  }
  if (!status) return <p className="text-xs text-terminal-muted">Loading…</p>;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-sm font-semibold">Upgrade</h1>
          <p className="text-xs text-terminal-muted">Pull the latest code, rebuild the containers, and restart — from here.</p>
        </div>
        <div className="flex items-center gap-2">
          {status.running && <span className="text-xs text-terminal-warn">Upgrade running…</span>}
          <button
            onClick={upgrade}
            disabled={starting || status.running || !status.configured}
            className="rounded bg-elavo-blue px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50">
            {status.running ? "Running…" : starting ? "Starting…" : "Upgrade now"}
          </button>
        </div>
      </div>

      {!status.configured && (
        <div className="panel text-xs text-terminal-bear">
          The upgrade agent is not configured on the host (the <code>/deploy</code> volume is not mounted).
        </div>
      )}
      {msg && <div className="text-xs text-terminal-muted">{msg}</div>}

      <div className="panel">
        <div className="panel-title">Status log</div>
        <pre ref={logRef} className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded bg-terminal-bg p-3 font-mono text-[11px] text-terminal-text">
{status.log || "No upgrade has run yet."}
        </pre>
      </div>
    </div>
  );
}
