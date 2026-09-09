"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet, apiPut, apiPost } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface ConfigItem {
  key: string;
  label: string;
  group: string;
  secret: boolean;
  testable: boolean;
  restart_required: boolean;
  placeholder: string;
  kind: "text" | "bool" | "number";
  help: string;
  has_value: boolean;
  display: string;
}
interface ConfigResponse { groups: string[]; items: ConfigItem[] }
type Msg = { ok: boolean; text: string };

export default function ConfigurationPage() {
  const { token } = useAuth();
  const [data, setData] = useState<ConfigResponse | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [msgs, setMsgs] = useState<Record<string, Msg>>({});
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [reloadMsg, setReloadMsg] = useState<string | null>(null);
  const [reloading, setReloading] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const res = await apiGet<ConfigResponse>("/admin/config", token);
      setData(res);
      // seed drafts: non-secrets prefilled with current value; secrets blank
      const d: Record<string, string> = {};
      res.items.forEach((i) => { d[i.key] = i.secret ? "" : i.display; });
      setDrafts(d);
    } catch {
      setForbidden(true);
    }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const setMsg = (key: string, m: Msg | null) =>
    setMsgs((s) => { const n = { ...s }; if (m) n[key] = m; else delete n[key]; return n; });

  async function save(item: ConfigItem) {
    if (!token) return;
    setBusy((b) => ({ ...b, [item.key]: true })); setMsg(item.key, null);
    try {
      await apiPut(`/admin/config/${item.key}`, { value: drafts[item.key] ?? "" }, token);
      setMsg(item.key, { ok: true, text: item.restart_required ? "Saved — restart api+worker to fully apply, or Reload." : "Saved. Click Reload to apply." });
      if (item.secret) setDrafts((s) => ({ ...s, [item.key]: "" }));
      load();
    } catch {
      setMsg(item.key, { ok: false, text: "Save failed." });
    } finally { setBusy((b) => ({ ...b, [item.key]: false })); }
  }

  async function test(item: ConfigItem) {
    if (!token) return;
    setBusy((b) => ({ ...b, [item.key + ":test"]: true })); setMsg(item.key, null);
    try {
      const r = await apiPost<{ ok: boolean; message: string }>(`/admin/config/${item.key}/test`, { value: drafts[item.key] ?? "" }, token);
      setMsg(item.key, { ok: r.ok, text: r.message ?? (r.ok ? "OK" : "Failed") });
    } catch {
      setMsg(item.key, { ok: false, text: "Test failed to run." });
    } finally { setBusy((b) => ({ ...b, [item.key + ":test"]: false })); }
  }

  async function reloadAll() {
    if (!token) return;
    setReloading(true); setReloadMsg(null);
    try {
      const r = await apiPost<{ applied: string[]; restart_required: string[] }>("/admin/config/reload", undefined, token);
      const restart = r.restart_required?.length ? ` — ${r.restart_required.length} setting(s) still need an api+worker restart: ${r.restart_required.join(", ")}` : "";
      setReloadMsg(`Applied ${r.applied?.length ?? 0} setting(s)${restart}`);
    } catch {
      setReloadMsg("Reload failed.");
    } finally { setReloading(false); }
  }

  if (forbidden) {
    return (
      <div className="panel max-w-md">
        <div className="panel-title">Configuration</div>
        <p className="text-xs text-terminal-muted">
          Configuration is reserved for a SUPER_ADMIN account — a standard ADMIN does not have the
          <code> admin.system_settings</code> permission.
        </p>
      </div>
    );
  }
  if (!data) return <p className="text-xs text-terminal-muted">Loading…</p>;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-sm font-semibold">Configuration</h1>
          <p className="text-xs text-terminal-muted">Environment settings (secrets encrypted at rest). Save, Test, then Reload to apply.</p>
        </div>
        <div className="flex items-center gap-2">
          {reloadMsg && <span className="text-xs text-terminal-muted">{reloadMsg}</span>}
          <button onClick={reloadAll} disabled={reloading}
            className="rounded bg-elavo-blue px-3 py-1.5 text-xs font-semibold text-white hover:opacity-90 disabled:opacity-50">
            {reloading ? "Reloading…" : "Reload configuration"}
          </button>
        </div>
      </div>

      {data.groups.map((group) => (
        <div key={group} className="panel">
          <div className="panel-title">{group}</div>
          <div className="divide-y divide-terminal-border/50">
            {data.items.filter((i) => i.group === group).map((item) => (
              <div key={item.key} className="py-2.5">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="w-56 shrink-0">
                    <div className="flex items-center gap-1.5 text-xs text-terminal-text">
                      {item.label}
                      {item.has_value
                        ? <span className="rounded bg-terminal-bull/15 px-1 py-px text-[9px] font-semibold uppercase tracking-wide text-terminal-bull">✓ set</span>
                        : <span className="rounded bg-terminal-muted/15 px-1 py-px text-[9px] font-semibold uppercase tracking-wide text-terminal-muted">not set</span>}
                    </div>
                    <div className="font-mono text-[10px] text-terminal-muted">{item.key}{item.restart_required ? " · restart" : ""}</div>
                  </div>
                  {item.kind === "bool" ? (
                    <select value={drafts[item.key] || "false"} onChange={(e) => setDrafts((s) => ({ ...s, [item.key]: e.target.value }))}
                      className="rounded border border-terminal-border bg-terminal-bg px-2 py-1 text-xs">
                      <option value="true">true</option>
                      <option value="false">false</option>
                    </select>
                  ) : (
                    <input
                      type={item.secret ? "password" : item.kind === "number" ? "number" : "text"}
                      value={drafts[item.key] ?? ""}
                      onChange={(e) => setDrafts((s) => ({ ...s, [item.key]: e.target.value }))}
                      placeholder={item.secret && item.has_value ? "•••••••• (set — type to change)" : item.placeholder}
                      className="min-w-0 flex-1 rounded border border-terminal-border bg-terminal-bg px-2 py-1 text-xs" />
                  )}
                  <button onClick={() => save(item)} disabled={busy[item.key]}
                    className="rounded border border-terminal-border px-2 py-1 text-xs hover:bg-terminal-bg disabled:opacity-50">
                    {busy[item.key] ? "…" : "Save"}
                  </button>
                  {item.testable && (
                    <button onClick={() => test(item)} disabled={busy[item.key + ":test"]}
                      className="rounded border border-terminal-border px-2 py-1 text-xs text-elavo-blue hover:bg-terminal-bg disabled:opacity-50">
                      {busy[item.key + ":test"] ? "Testing…" : "Test"}
                    </button>
                  )}
                </div>
                {item.help && <div className="mt-0.5 pl-1 text-[10px] text-terminal-muted">{item.help}</div>}
                {msgs[item.key] && (
                  <div className={`mt-0.5 pl-1 text-[10px] ${msgs[item.key].ok ? "text-terminal-bull" : "text-terminal-bear"}`}>{msgs[item.key].text}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
