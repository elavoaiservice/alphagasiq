"use client";

import { useEffect, useState } from "react";
import { API_BASE, apiGet, apiPost } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface Organization {
  id: string;
  name: string;
  country: string | null;
  status: string;
  billing_plan: string | null;
  data_entitlements: Record<string, unknown>;
}

export default function AdminOrganizationsPage() {
  const { token } = useAuth();
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [newName, setNewName] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [entitlementsDraft, setEntitlementsDraft] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  async function refresh() {
    if (!token) return;
    setOrganizations(await apiGet<Organization[]>("/admin/organizations", token));
  }

  useEffect(() => {
    refresh().catch(() => setMessage("Unable to load organizations."));
  }, [token]);

  async function createOrganization(e: React.FormEvent) {
    e.preventDefault();
    if (!token || !newName.trim()) return;
    try {
      await apiPost("/admin/organizations", { name: newName }, token);
      setNewName("");
      await refresh();
    } catch {
      setMessage("Could not create organization — the name may already be in use.");
    }
  }

  function startEditingEntitlements(org: Organization) {
    setEditing(org.id);
    setEntitlementsDraft(JSON.stringify(org.data_entitlements ?? {}, null, 2));
  }

  async function saveEntitlements(orgId: string) {
    if (!token) return;
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(entitlementsDraft);
    } catch {
      setMessage("Data entitlements must be valid JSON.");
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/admin/organizations/${orgId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ data_entitlements: parsed }),
      });
      if (!res.ok) throw new Error();
      setEditing(null);
      await refresh();
    } catch {
      setMessage("Could not save data entitlements.");
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="panel-title">Organizations</h1>

      <form onSubmit={createOrganization} className="panel flex gap-2">
        <input
          required
          placeholder="Organization name"
          className="flex-1 bg-terminal-bg border border-terminal-border rounded px-2 py-1 text-xs"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
        />
        <button
          type="submit"
          className="text-xs px-3 py-1 border border-terminal-accent text-terminal-accent rounded hover:bg-terminal-accent/10"
        >
          Create
        </button>
      </form>
      {message && <p className="text-xs text-terminal-warn">{message}</p>}

      <div className="space-y-2">
        {organizations.map((org) => (
          <div key={org.id} className="panel">
            <div className="flex items-center justify-between">
              <div>
                <span className="font-medium">{org.name}</span>{" "}
                <span className="text-[10px] text-terminal-muted">
                  {org.status} · {org.country ?? "—"} · {org.billing_plan ?? "no plan"}
                </span>
              </div>
              <button
                onClick={() => startEditingEntitlements(org)}
                className="text-[10px] px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-accent"
              >
                Edit Data Entitlements
              </button>
            </div>
            {editing === org.id && (
              <div className="mt-2 space-y-2">
                <textarea
                  rows={5}
                  className="w-full bg-terminal-bg border border-terminal-border rounded px-2 py-1 text-xs font-mono"
                  value={entitlementsDraft}
                  onChange={(e) => setEntitlementsDraft(e.target.value)}
                />
                <div className="flex gap-2">
                  <button
                    onClick={() => saveEntitlements(org.id)}
                    className="text-[10px] px-2 py-1 border border-terminal-accent text-terminal-accent rounded"
                  >
                    Save
                  </button>
                  <button
                    onClick={() => setEditing(null)}
                    className="text-[10px] px-2 py-1 border border-terminal-border rounded"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
