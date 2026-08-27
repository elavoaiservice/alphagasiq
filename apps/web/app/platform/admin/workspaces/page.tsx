"use client";

import { useEffect, useState } from "react";
import { apiDelete, apiGet, apiPost } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface Organization {
  id: string;
  name: string;
}

interface Workspace {
  id: string;
  organization_id: string;
  name: string;
  description: string;
  created_by: string | null;
  created_at: string;
}

interface WorkspaceMember {
  workspace_id: string;
  user_id: string;
  added_by: string | null;
  added_at: string;
}

function WorkspaceDetail({ workspace, token, onChanged }: { workspace: Workspace; token: string; onChanged: () => void }) {
  const [members, setMembers] = useState<WorkspaceMember[] | null>(null);
  const [newUserId, setNewUserId] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  async function loadMembers() {
    setMembers(await apiGet<WorkspaceMember[]>(`/admin/workspaces/${workspace.id}/members`, token));
  }

  useEffect(() => {
    loadMembers().catch(() => setMessage("Unable to load members."));
  }, [workspace.id, token]);

  async function addMember() {
    if (!newUserId.trim()) return;
    setMessage(null);
    try {
      await apiPost(`/admin/workspaces/${workspace.id}/members`, { user_id: newUserId.trim() }, token);
      setNewUserId("");
      await loadMembers();
    } catch {
      setMessage("Could not add member — check the user id.");
    }
  }

  async function removeMember(userId: string) {
    setMessage(null);
    try {
      await apiDelete(`/admin/workspaces/${workspace.id}/members/${userId}`, token);
      await loadMembers();
    } catch {
      setMessage("Could not remove member.");
    }
  }

  return (
    <div className="panel space-y-3">
      <div className="panel-title">{workspace.name}</div>
      <p className="text-[11px] text-terminal-muted">{workspace.description || "No description."}</p>
      {message && <p className="text-xs text-terminal-warn">{message}</p>}

      <div className="flex items-center gap-2 text-xs">
        <input
          className="bg-terminal-bg border border-terminal-border rounded px-2 py-1"
          placeholder="user id"
          value={newUserId}
          onChange={(e) => setNewUserId(e.target.value)}
        />
        <button
          onClick={addMember}
          className="px-2 py-1 border border-terminal-border rounded hover:border-terminal-accent"
        >
          Add member
        </button>
      </div>

      <table className="mono-table w-full text-xs">
        <thead>
          <tr>
            <th>User ID</th>
            <th>Added By</th>
            <th>Added At</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {(members ?? []).map((m) => (
            <tr key={m.user_id}>
              <td>{m.user_id}</td>
              <td>{m.added_by ?? "—"}</td>
              <td>{new Date(m.added_at).toLocaleString()}</td>
              <td>
                <button
                  onClick={() => removeMember(m.user_id)}
                  className="text-[10px] px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-bear hover:text-terminal-bear"
                >
                  Remove
                </button>
              </td>
            </tr>
          ))}
          {members?.length === 0 && (
            <tr>
              <td colSpan={4} className="text-terminal-muted">
                No members yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export default function AdminWorkspacesPage() {
  const { token } = useAuth();
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [draft, setDraft] = useState({ organization_id: "", name: "", description: "" });

  async function refresh() {
    if (!token) return;
    setWorkspaces(await apiGet<Workspace[]>("/admin/workspaces", token));
  }

  useEffect(() => {
    if (!token) return;
    refresh().catch(() => setMessage("Unable to load workspaces."));
    apiGet<Organization[]>("/admin/organizations", token).then(setOrganizations).catch(() => {});
  }, [token]);

  async function createWorkspace() {
    if (!token || !draft.organization_id || !draft.name.trim()) return;
    setMessage(null);
    try {
      await apiPost("/admin/workspaces", draft, token);
      setDraft({ organization_id: "", name: "", description: "" });
      await refresh();
    } catch {
      setMessage("Could not create workspace.");
    }
  }

  async function deleteWorkspace(id: string) {
    if (!token) return;
    try {
      await apiDelete(`/admin/workspaces/${id}`, token);
      if (selected === id) setSelected(null);
      await refresh();
    } catch {
      setMessage("Could not delete workspace.");
    }
  }

  if (!workspaces) return <p className="text-xs text-terminal-muted">Loading…</p>;

  const activeWorkspace = workspaces.find((w) => w.id === selected) ?? null;

  return (
    <div className="space-y-4">
      <h1 className="panel-title">Workspaces</h1>
      <p className="text-[11px] text-terminal-muted">
        A grouping inside an Organization (docs/alpha-intelligence.md section 11.1) that
        enterprise data sources, datasets, and entitlements can be scoped to.
      </p>
      {message && <p className="text-xs text-terminal-bear">{message}</p>}

      <div className="panel flex flex-wrap items-end gap-2 text-xs">
        <label className="flex flex-col gap-1">
          Organization
          <select
            className="bg-terminal-bg border border-terminal-border rounded px-2 py-1"
            value={draft.organization_id}
            onChange={(e) => setDraft((d) => ({ ...d, organization_id: e.target.value }))}
          >
            <option value="">Select…</option>
            {organizations.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          Name
          <input
            className="bg-terminal-bg border border-terminal-border rounded px-2 py-1"
            value={draft.name}
            onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
          />
        </label>
        <label className="flex flex-col gap-1">
          Description
          <input
            className="bg-terminal-bg border border-terminal-border rounded px-2 py-1"
            value={draft.description}
            onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
          />
        </label>
        <button
          onClick={createWorkspace}
          className="px-2 py-1 border border-terminal-accent text-terminal-accent rounded hover:bg-terminal-accent/10"
        >
          Create workspace
        </button>
      </div>

      <div className="panel overflow-x-auto">
        <table className="mono-table w-full">
          <thead>
            <tr>
              <th>Name</th>
              <th>Organization</th>
              <th>Created At</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {workspaces.map((w) => (
              <tr key={w.id}>
                <td>{w.name}</td>
                <td>{organizations.find((o) => o.id === w.organization_id)?.name ?? w.organization_id}</td>
                <td className="whitespace-nowrap">{new Date(w.created_at).toLocaleString()}</td>
                <td className="flex gap-2">
                  <button
                    onClick={() => setSelected(w.id === selected ? null : w.id)}
                    className="text-[10px] px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-accent"
                  >
                    {w.id === selected ? "Close" : "Manage"}
                  </button>
                  <button
                    onClick={() => deleteWorkspace(w.id)}
                    className="text-[10px] px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-bear hover:text-terminal-bear"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            {workspaces.length === 0 && (
              <tr>
                <td colSpan={4} className="text-terminal-muted">
                  No workspaces yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {activeWorkspace && <WorkspaceDetail workspace={activeWorkspace} token={token!} onChanged={refresh} />}
    </div>
  );
}
