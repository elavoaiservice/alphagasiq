"use client";

import { useEffect, useState } from "react";
import { API_BASE, apiGet } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface Feature {
  key: string;
  name: string;
  security_sensitive: boolean;
  globally_enabled: boolean;
}

const ROLES = ["SUPER_ADMIN", "ADMIN", "TRADER", "RISK_MANAGER", "RESEARCHER", "EXECUTIVE", "VIEWER", "API_USER"];

export default function AdminFeaturesPage() {
  const { token } = useAuth();
  const [features, setFeatures] = useState<Feature[]>([]);
  const [role, setRole] = useState("TRADER");
  const [roleGrants, setRoleGrants] = useState<Record<string, boolean>>({});
  const [message, setMessage] = useState<string | null>(null);

  async function refreshFeatures() {
    if (!token) return;
    setFeatures(await apiGet<Feature[]>("/admin/features", token));
  }

  async function refreshRoleGrants(forRole: string) {
    if (!token) return;
    const data = await apiGet<{ features: Record<string, boolean> }>(`/admin/roles/${forRole}/features`, token);
    setRoleGrants(data.features);
  }

  useEffect(() => {
    refreshFeatures().catch(() => setMessage("Unable to load features."));
  }, [token]);

  useEffect(() => {
    refreshRoleGrants(role).catch(() => setMessage("Unable to load role feature grants."));
  }, [token, role]);

  async function toggleGlobal(key: string, enabled: boolean) {
    if (!token) return;
    await fetch(`${API_BASE}/admin/features/${key}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ enabled }),
    });
    await refreshFeatures();
  }

  async function toggleRoleGrant(key: string, enabled: boolean) {
    if (!token) return;
    await fetch(`${API_BASE}/admin/roles/${role}/features/${key}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ enabled }),
    });
    await refreshRoleGrants(role);
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="panel-title">Feature Management — Global</h1>
        {message && <p className="text-xs text-terminal-warn">{message}</p>}
        <div className="panel overflow-x-auto mt-2">
          <table className="mono-table w-full">
            <thead>
              <tr>
                <th>Feature</th>
                <th>Security Sensitive</th>
                <th>Globally Enabled</th>
              </tr>
            </thead>
            <tbody>
              {features.map((f) => (
                <tr key={f.key}>
                  <td>{f.name}</td>
                  <td>{f.security_sensitive ? "Yes" : "No"}</td>
                  <td>
                    <input
                      type="checkbox"
                      checked={f.globally_enabled}
                      onChange={(e) => toggleGlobal(f.key, e.target.checked)}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between">
          <h2 className="panel-title">Role Grants</h2>
          <select
            className="bg-terminal-bg border border-terminal-border rounded px-2 py-1 text-xs"
            value={role}
            onChange={(e) => setRole(e.target.value)}
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </div>
        <div className="panel overflow-x-auto mt-2">
          <table className="mono-table w-full">
            <thead>
              <tr>
                <th>Feature</th>
                <th>Granted to {role}</th>
              </tr>
            </thead>
            <tbody>
              {features.map((f) => (
                <tr key={f.key}>
                  <td>{f.name}</td>
                  <td>
                    <input
                      type="checkbox"
                      checked={roleGrants[f.key] ?? false}
                      onChange={(e) => toggleRoleGrant(f.key, e.target.checked)}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
