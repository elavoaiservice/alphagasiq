"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface AuditEvent {
  id: string;
  actor_user_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  reason: string | null;
  occurred_at: string;
}

const RESOURCE_TYPES = ["", "agent", "agent_version", "model_definition", "risk_limits", "user"];

export default function AdminAuditLogPage() {
  const { token } = useAuth();
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [resourceType, setResourceType] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    const query = resourceType ? `?resource_type=${resourceType}` : "";
    apiGet<AuditEvent[]>(`/admin/audit-logs${query}`, token)
      .then(setEvents)
      .catch(() => setMessage("Unable to load audit log."));
  }, [token, resourceType]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="panel-title">Audit Log</h1>
        <select
          value={resourceType}
          onChange={(e) => setResourceType(e.target.value)}
          className="bg-terminal-bg border border-terminal-border rounded px-2 py-1 text-xs"
        >
          {RESOURCE_TYPES.map((t) => (
            <option key={t} value={t}>
              {t || "All resource types"}
            </option>
          ))}
        </select>
      </div>
      <p className="text-[11px] text-terminal-muted">
        Append-only — there is no update or delete action for any entry here, ever (spec §55).
      </p>
      {message && <p className="text-xs text-terminal-bear">{message}</p>}
      {!events ? (
        <p className="text-xs text-terminal-muted">Loading…</p>
      ) : (
        <div className="panel overflow-x-auto">
          <table className="mono-table w-full text-xs">
            <thead>
              <tr>
                <th>Time</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Resource</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {events.length === 0 && (
                <tr>
                  <td colSpan={5} className="text-terminal-muted">
                    No audit events recorded yet.
                  </td>
                </tr>
              )}
              {events.map((e) => (
                <tr key={e.id}>
                  <td className="whitespace-nowrap">{new Date(e.occurred_at).toLocaleString()}</td>
                  <td>{e.actor_user_id ?? "system"}</td>
                  <td>{e.action}</td>
                  <td>
                    {e.resource_type}: {e.resource_id}
                  </td>
                  <td>{e.reason ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
