"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface Status { configured: boolean; running: boolean; log: string }

interface Commit {
  commit?: string; commit_short?: string; subject?: string;
  author?: string; committed_at?: string; branch?: string; built_at?: string;
}
interface Incoming { sha: string; subject: string; author?: string; committed_at?: string }
interface Version {
  repo: string; branch: string; environment: string;
  running: Commit; checkout: Commit; remote: Commit & { error?: string };
  up_to_date: boolean; rebuild_required: boolean;
  incoming: Incoming[]; incoming_count: number;
}

function when(iso?: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "" : d.toLocaleString();
}

/** 12-char sha in mono, matching the ElavoFishAI version card. */
function Sha({ value }: { value?: string }) {
  if (!value) return <span className="text-terminal-muted">unknown</span>;
  return <span className="font-mono text-[13px] text-terminal-text">{value.slice(0, 12)}</span>;
}

function VersionCard({ v, running }: { v: Version; running: boolean }) {
  const { remote, running: cur, incoming } = v;

  const badge = remote.error ? (
    <span className="rounded-full bg-terminal-bg px-2 py-0.5 text-[11px] font-semibold text-terminal-muted">
      can’t reach remote
    </span>
  ) : v.up_to_date ? (
    <span className="rounded-full bg-terminal-bull/10 px-2 py-0.5 text-[11px] font-semibold text-terminal-bull">
      ✓ Up to date
    </span>
  ) : (
    <span className="rounded-full bg-terminal-warn/15 px-2 py-0.5 text-[11px] font-semibold text-terminal-warn">
      ↑ {v.incoming_count} behind
    </span>
  );

  return (
    <div className="panel">
      <div className="mb-3.5 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold">Version</h2>
          {badge}
        </div>
        <code className="font-mono text-[11px] text-terminal-muted">{v.repo}</code>
      </div>

      <div className="grid gap-4 text-sm sm:grid-cols-2">
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-terminal-muted">Current</div>
          <div><Sha value={cur.commit} /></div>
          {cur.subject && <div className="mt-0.5 text-[11px] text-terminal-muted">{cur.subject}</div>}
          {cur.branch && <div className="text-[11px] text-terminal-muted">built from {cur.branch}</div>}
          {cur.built_at && <div className="text-[11px] text-terminal-muted">built {when(cur.built_at)}</div>}
        </div>
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-terminal-muted">
            Remote ({v.branch})
          </div>
          <div><Sha value={remote.commit} /></div>
          {remote.subject && <div className="mt-0.5 text-[11px] text-terminal-muted">{remote.subject}</div>}
          {remote.committed_at && (
            <div className="text-[11px] text-terminal-muted">pushed {when(remote.committed_at)}</div>
          )}
          {remote.error && <div className="mt-0.5 text-[11px] text-terminal-bear">{remote.error}</div>}
        </div>
      </div>

      {/* AlphaGasIQ-only: the host pulled but the image was never rebuilt, so the
          running code is older than the checkout. ElavoFishAI has no equivalent
          because its deploy has no separate build step. */}
      {v.rebuild_required && (
        <div className="mt-3.5 rounded border border-terminal-warn/40 bg-terminal-warn/10 p-2.5 text-[11px] text-terminal-warn">
          The host has checked out <code className="font-mono">{v.checkout.commit?.slice(0, 12)}</code> but
          this image was built from <code className="font-mono">{cur.commit?.slice(0, 12)}</code>. A restart
          is not enough — run an upgrade so the image is rebuilt.
        </div>
      )}

      {remote.error ? null : v.up_to_date ? (
        <div className="mt-3.5 rounded border border-terminal-bull/30 bg-terminal-bull/10 p-2.5 text-xs text-terminal-bull">
          ✓ You’re running the latest {v.branch}.
        </div>
      ) : !cur.commit ? (
        <div className="mt-3.5 text-[11px] text-terminal-muted">
          Current build has no version stamp yet — it will appear after the next deploy.
        </div>
      ) : incoming.length ? (
        <>
          <div className="mb-1.5 mt-4 text-[11px] uppercase tracking-wide text-terminal-muted">
            Incoming ({incoming.length} commit{incoming.length === 1 ? "" : "s"})
          </div>
          <div className="max-h-[220px] overflow-auto rounded-[10px] border border-terminal-border bg-terminal-bg px-3 py-2.5 text-xs">
            {incoming.map((c) => (
              <div key={c.sha} className="flex gap-2.5 py-0.5">
                <span className="shrink-0 font-mono text-terminal-muted">{c.sha}</span>
                <span className="min-w-0 flex-1 truncate">{c.subject}</span>
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className="mt-3.5 text-[11px] text-terminal-muted">
          The running build differs from <b>{v.branch}</b> (commit list unavailable — the current build
          may be ahead of, or not pushed to, the remote).
        </div>
      )}

      {running && <div className="mt-3 text-xs text-terminal-warn">Upgrade running…</div>}
    </div>
  );
}

export default function UpgradePage() {
  const { token } = useAuth();
  const [status, setStatus] = useState<Status | null>(null);
  const [version, setVersion] = useState<Version | null>(null);
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
      return;
    }
    // Separate call: a GitHub outage must never blank out the status log.
    try {
      setVersion(await apiGet<Version>("/admin/upgrade/version", token));
    } catch {
      /* keep the previous reading rather than flashing the card empty */
    }
  }, [token]);

  useEffect(() => {
    poll();
    const id = setInterval(poll, 3000);
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

  // Mirrors ElavoFishAI: the button names the exact commit it will move you to.
  const target = version && !version.up_to_date && !version.remote.error ? version.remote.commit : undefined;
  const buttonLabel = status.running
    ? "Running…"
    : starting
      ? "Starting…"
      : target
        ? `Upgrade to ${target.slice(0, 7)}`
        : "Upgrade now";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-sm font-semibold">Upgrade</h1>
          <p className="text-xs text-terminal-muted">Pull the latest code, rebuild the containers, and restart — from here.</p>
        </div>
        <button
          onClick={upgrade}
          disabled={starting || status.running || !status.configured}
          className="rounded bg-elavo-blue px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50">
          {buttonLabel}
        </button>
      </div>

      {version ? (
        <VersionCard v={version} running={status.running} />
      ) : (
        <div className="panel text-xs text-terminal-muted">Loading version…</div>
      )}

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
