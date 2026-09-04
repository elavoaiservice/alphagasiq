"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface AdminUser {
  id: string;
  first_name: string;
  last_name: string;
  email: string;
  organization_name: string | null;
  role_name: string | null;
  status: string;
  last_login_at: string | null;
  created_at: string;
  expiration_at: string | null;
}

interface Role {
  id: string;
  name: string;
  description: string | null;
}

const NEW_USER_DEFAULTS = {
  first_name: "",
  last_name: "",
  business_email: "",
  company_name: "",
  role: "VIEWER",
};

// spec §17: which admin-facing status transitions apply from each current status.
const STATUS_ACTIONS: Record<string, string[]> = {
  ACTIVE: ["SUSPENDED", "DISABLED", "REVOKED"],
  SUSPENDED: ["ACTIVE", "REVOKED"],
  DISABLED: ["ACTIVE", "REVOKED"],
  LOCKED: ["ACTIVE", "REVOKED"],
  EXPIRED: ["ACTIVE", "REVOKED"],
  INVITED: ["REVOKED"],
  REVOKED: [],
};

export default function AdminUsersPage() {
  const { token } = useAuth();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [form, setForm] = useState(NEW_USER_DEFAULTS);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function refresh() {
    if (!token) return;
    const [userList, roleList] = await Promise.all([
      apiGet<AdminUser[]>("/admin/users", token),
      apiGet<Role[]>("/admin/roles", token),
    ]);
    setUsers(userList);
    setRoles(roleList);
  }

  useEffect(() => {
    refresh().catch(() => setMessage("Unable to load users."));
  }, [token]);

  async function createUser(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    setBusy("create");
    setMessage(null);
    try {
      await apiPost("/admin/users", form, token);
      setForm(NEW_USER_DEFAULTS);
      setMessage(`Invitation sent to ${form.business_email}.`);
      await refresh();
    } catch {
      setMessage("Could not create user — check the email isn't already in use.");
    } finally {
      setBusy(null);
    }
  }

  async function changeStatus(userId: string, newStatus: string) {
    if (!token) return;
    setBusy(userId);
    try {
      await apiPost(`/admin/users/${userId}/status`, { status: newStatus }, token);
      await refresh();
    } catch {
      setMessage("Status change failed.");
    } finally {
      setBusy(null);
    }
  }

  async function resendInvitation(userId: string) {
    if (!token) return;
    setBusy(userId);
    try {
      await apiPost(`/admin/users/${userId}/resend-invitation`, undefined, token);
      setMessage("Invitation resent.");
    } catch {
      setMessage("Could not resend invitation.");
    } finally {
      setBusy(null);
    }
  }

  async function sendLoginLink(userId: string) {
    if (!token) return;
    setBusy(userId);
    try {
      await apiPost(`/admin/users/${userId}/send-login-link`, undefined, token);
      setMessage("Login link sent.");
    } catch {
      setMessage("Could not send login link.");
    } finally {
      setBusy(null);
    }
  }

  const inputClass = "w-full bg-terminal-bg border border-terminal-border rounded px-2 py-1 text-xs";

  return (
    <div className="space-y-4">
      <h1 className="panel-title">Users</h1>

      <form onSubmit={createUser} className="panel grid grid-cols-2 md:grid-cols-3 gap-2">
        <input
          required
          placeholder="First name"
          className={inputClass}
          value={form.first_name}
          onChange={(e) => setForm((f) => ({ ...f, first_name: e.target.value }))}
        />
        <input
          required
          placeholder="Last name"
          className={inputClass}
          value={form.last_name}
          onChange={(e) => setForm((f) => ({ ...f, last_name: e.target.value }))}
        />
        <input
          required
          type="email"
          placeholder="Business email"
          className={inputClass}
          value={form.business_email}
          onChange={(e) => setForm((f) => ({ ...f, business_email: e.target.value }))}
        />
        <input
          required
          placeholder="Company name"
          className={inputClass}
          value={form.company_name}
          onChange={(e) => setForm((f) => ({ ...f, company_name: e.target.value }))}
        />
        <select
          className={inputClass}
          value={form.role}
          onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}
        >
          {roles.map((r) => (
            <option key={r.id} value={r.name}>
              {r.name}
            </option>
          ))}
        </select>
        <button
          type="submit"
          disabled={busy === "create"}
          className="text-xs px-3 py-1 border border-terminal-accent text-terminal-accent rounded hover:bg-terminal-accent/10 disabled:opacity-50"
        >
          Create User
        </button>
      </form>
      {message && <p className="text-xs text-terminal-warn">{message}</p>}

      <div className="panel overflow-x-auto">
        <table className="mono-table w-full">
          <thead>
            <tr>
              <th>Name</th>
              <th>Email</th>
              <th>Company</th>
              <th>Role</th>
              <th>Status</th>
              <th>Last Login</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id}>
                <td>
                  {u.first_name} {u.last_name}
                </td>
                <td>{u.email}</td>
                <td>{u.organization_name}</td>
                <td>{u.role_name}</td>
                <td>{u.status}</td>
                <td>{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "Never"}</td>
                <td className="flex flex-wrap gap-1">
                  {(STATUS_ACTIONS[u.status] ?? []).map((target) => (
                    <button
                      key={target}
                      disabled={busy === u.id}
                      onClick={() => changeStatus(u.id, target)}
                      className="text-[10px] px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-accent disabled:opacity-50"
                    >
                      {target}
                    </button>
                  ))}
                  {u.status === "INVITED" && (
                    <button
                      disabled={busy === u.id}
                      onClick={() => resendInvitation(u.id)}
                      className="text-[10px] px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-accent disabled:opacity-50"
                    >
                      Resend Invitation
                    </button>
                  )}
                  {u.status === "ACTIVE" && (
                    <button
                      disabled={busy === u.id}
                      onClick={() => sendLoginLink(u.id)}
                      className="text-[10px] px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-accent disabled:opacity-50"
                    >
                      Send Login Link
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
