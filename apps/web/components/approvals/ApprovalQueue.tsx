"use client";

import { useEffect, useState } from "react";
import { API_BASE, apiPost } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface Approval {
  id: string;
  trade_id: string;
  state: string;
  updated_at: string;
}

const PENDING_STATES = new Set(["HUMAN_REVIEW", "AI_REVIEW"]);

export function ApprovalQueue() {
  const { token, user } = useAuth();
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function refresh() {
    const res = await fetch(`${API_BASE}/approvals`);
    setApprovals(await res.json());
  }

  useEffect(() => {
    refresh();
  }, []);

  async function act(id: string, action: "APPROVE" | "REJECT") {
    if (!token) {
      setMessage("Sign in as a Trader/Risk Manager/Admin to act on approvals.");
      return;
    }
    setBusyId(id);
    setMessage(null);
    try {
      await apiPost(`/approvals/${id}/action`, { action, payload: { quantity: 10 } }, token);
      await refresh();
    } catch {
      setMessage("Action failed — the Risk Governor may not have cleared this trade yet.");
    } finally {
      setBusyId(null);
    }
  }

  const pending = approvals.filter((a) => PENDING_STATES.has(a.state));

  return (
    <div className="panel">
      <div className="panel-title">Approval Queue</div>
      {!user && (
        <div className="text-[10px] text-terminal-muted mb-2">
          Viewing as anonymous — sign in (top right) to approve or reject.
        </div>
      )}
      {pending.length === 0 ? (
        <div className="text-xs text-terminal-muted">No trades pending human review.</div>
      ) : (
        <div className="space-y-2">
          {pending.map((a) => (
            <div key={a.id} className="flex items-center justify-between text-xs border border-terminal-border rounded p-1.5">
              <div>
                <div className="font-mono">{a.trade_id.slice(0, 8)}…</div>
                <div className="text-terminal-muted">{a.state}</div>
              </div>
              <div className="flex gap-1">
                <button
                  disabled={busyId === a.id}
                  onClick={() => act(a.id, "APPROVE")}
                  className="px-2 py-1 border border-terminal-bull text-terminal-bull rounded hover:bg-terminal-bull/10 disabled:opacity-50"
                >
                  Approve
                </button>
                <button
                  disabled={busyId === a.id}
                  onClick={() => act(a.id, "REJECT")}
                  className="px-2 py-1 border border-terminal-bear text-terminal-bear rounded hover:bg-terminal-bear/10 disabled:opacity-50"
                >
                  Reject
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
      {message && <div className="mt-2 text-[10px] text-terminal-warn">{message}</div>}
    </div>
  );
}
