"use client";

import { useEffect, useState } from "react";
import { API_BASE, apiGet } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface SystemSetting {
  key: string;
  value: unknown;
  version: number;
  updated_by: string | null;
  updated_at: string;
}

export default function AdminSettingsPage() {
  const { token } = useAuth();
  const [settings, setSettings] = useState<SystemSetting[] | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [forbidden, setForbidden] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function refresh() {
    if (!token) return;
    try {
      const list = await apiGet<SystemSetting[]>("/admin/settings", token);
      setSettings(list);
      setDrafts(Object.fromEntries(list.map((s) => [s.key, JSON.stringify(s.value)])));
      setForbidden(false);
    } catch (err) {
      if (err instanceof Error && err.message.includes("403")) setForbidden(true);
      else setMessage("Unable to load system settings.");
    }
  }

  useEffect(() => {
    refresh();
  }, [token]);

  async function save(key: string) {
    if (!token) return;
    let value: unknown;
    try {
      value = JSON.parse(drafts[key]);
    } catch {
      setMessage(`"${key}" must be valid JSON (wrap plain text in quotes).`);
      return;
    }
    const res = await fetch(`${API_BASE}/admin/settings/${key}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ value }),
    });
    if (!res.ok) {
      setMessage(`Could not update "${key}".`);
      return;
    }
    await refresh();
  }

  if (forbidden) {
    return (
      <div className="panel max-w-md">
        <div className="panel-title">System Configuration</div>
        <p className="text-xs text-terminal-muted">
          System settings are reserved for a SUPER_ADMIN account (spec §38 / docs/access-model.md
          §5) — a standard ADMIN does not have the <code>admin.system_settings</code> permission.
        </p>
      </div>
    );
  }

  if (!settings) return <p className="text-xs text-terminal-muted">Loading…</p>;

  return (
    <div className="space-y-4">
      <h1 className="panel-title">System Configuration</h1>
      <p className="text-[11px] text-terminal-muted">
        Every change here is versioned and reversible via history (spec §38) — see each setting's
        version number below.
      </p>
      {message && <p className="text-xs text-terminal-warn">{message}</p>}
      <div className="panel overflow-x-auto">
        <table className="mono-table w-full">
          <thead>
            <tr>
              <th>Key</th>
              <th>Value (JSON)</th>
              <th>Version</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {settings.map((s) => (
              <tr key={s.key}>
                <td className="whitespace-nowrap">{s.key}</td>
                <td>
                  <input
                    className="w-full bg-terminal-bg border border-terminal-border rounded px-2 py-1 text-xs font-mono"
                    value={drafts[s.key] ?? ""}
                    onChange={(e) => setDrafts((d) => ({ ...d, [s.key]: e.target.value }))}
                  />
                </td>
                <td>{s.version}</td>
                <td>
                  <button
                    onClick={() => save(s.key)}
                    className="text-[10px] px-1.5 py-0.5 border border-terminal-accent text-terminal-accent rounded"
                  >
                    Save
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
