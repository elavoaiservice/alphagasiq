"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import { useLiveRefetch } from "@/lib/live-events-context";

interface EnterpriseOpportunity {
  id: string;
  organization_id: string;
  opportunity_type: "HEDGE_MISALIGNED_POSITION" | "NEW_POSITION_HIGH_CONVICTION_SIGNAL";
  market: string;
  title: string;
  summary: string;
  confidence: number;
  status: "PENDING" | "APPROVED" | "REJECTED";
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
}

const STATUS_COLOR: Record<string, string> = {
  PENDING: "text-terminal-muted",
  APPROVED: "text-terminal-bull",
  REJECTED: "text-terminal-bear",
};

export function OpportunitiesTable() {
  const { token } = useAuth();
  const [opportunities, setOpportunities] = useState<EnterpriseOpportunity[] | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [reviewMessage, setReviewMessage] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  function load() {
    if (!token) return;
    apiGet<EnterpriseOpportunity[]>("/alpha/enterprise/opportunities", token)
      .then(setOpportunities)
      .catch(() =>
        setMessage("Unable to load enterprise opportunities — this requires the 'enterprise_opportunities.view' permission.")
      );
  }

  useEffect(load, [token]);
  // Worker-generated opportunities arrive on their own cadence — push, don't poll.
  useLiveRefetch(["OPPORTUNITY_PROPOSED"], load);

  async function generate() {
    if (!token) return;
    setGenerating(true);
    setMessage(null);
    try {
      await apiPost("/alpha/enterprise/opportunities/generate", {}, token);
      load();
    } catch {
      setMessage(
        "Unable to generate opportunities — this requires the 'enterprise_opportunities.generate' permission and a resolvable organization."
      );
    } finally {
      setGenerating(false);
    }
  }

  async function review(id: string, status: "APPROVED" | "REJECTED") {
    if (!token) return;
    setReviewMessage(null);
    try {
      const updated = await apiPost<EnterpriseOpportunity>(`/alpha/enterprise/opportunities/${id}/review`, { status }, token);
      setOpportunities((prev) => (prev ? prev.map((o) => (o.id === updated.id ? updated : o)) : prev));
    } catch {
      setReviewMessage("Unable to review — this requires the 'enterprise_opportunities.review' permission.");
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="panel-title">Enterprise Opportunities</h1>
        <button
          onClick={generate}
          disabled={generating}
          className="text-[10px] px-2 py-1 border border-terminal-border rounded hover:border-terminal-accent disabled:opacity-50"
        >
          {generating ? "Generating…" : "Generate"}
        </button>
      </div>
      <p className="text-[11px] text-terminal-muted">
        Candidate opportunities the Enterprise Opportunity Engine drafted by cross-referencing your
        organization&apos;s own proprietary position data against the Alpha Intelligence Layer&apos;s signals and
        consensus views — always human-reviewed, never auto-executed into a trade or position change.
      </p>
      {message && <p className="text-xs text-terminal-bear">{message}</p>}
      {reviewMessage && <p className="text-xs text-terminal-bear">{reviewMessage}</p>}

      {!opportunities ? (
        <p className="text-xs text-terminal-muted">Loading…</p>
      ) : opportunities.length === 0 ? (
        <div className="panel">
          <div className="text-xs text-terminal-muted">
            No opportunities yet — click Generate to run the engine against your organization&apos;s registered
            position data.
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {opportunities.map((o) => (
            <div key={o.id} className="panel">
              <div className="flex items-center justify-between mb-1">
                <div className="panel-title">{o.title}</div>
                <span className={STATUS_COLOR[o.status]}>{o.status}</span>
              </div>
              <div className="text-xs mb-2">{o.summary}</div>
              <div className="text-[10px] text-terminal-muted mb-2">
                {o.opportunity_type} · {o.market} · confidence {(o.confidence * 100).toFixed(0)}%
              </div>
              {o.status === "PENDING" && (
                <div className="flex items-center gap-2 text-[10px]">
                  <button
                    onClick={() => review(o.id, "APPROVED")}
                    className="px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-bull hover:text-terminal-bull"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => review(o.id, "REJECTED")}
                    className="px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-bear hover:text-terminal-bear"
                  >
                    Reject
                  </button>
                </div>
              )}
              {o.reviewed_by && <div className="text-[10px] text-terminal-muted mt-1">reviewed by {o.reviewed_by}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
