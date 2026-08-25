"use client";

import { useState } from "react";
import { apiPost } from "@/lib/api-client";

interface ChallengeResponse {
  bear_case: string;
  skeptic_case: string;
  unresolved_questions: string[];
}

export function ChallengeAiButton({ tradeId }: { tradeId: string }) {
  const [result, setResult] = useState<ChallengeResponse | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleClick() {
    setLoading(true);
    try {
      const res = await apiPost<ChallengeResponse>(`/trade-ideas/${tradeId}/challenge`);
      setResult(res);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <button
        onClick={handleClick}
        disabled={loading}
        className="text-xs px-2 py-1 border border-terminal-accent text-terminal-accent rounded hover:bg-terminal-accent/10 disabled:opacity-50"
      >
        {loading ? "Challenging..." : "Challenge AI"}
      </button>
      {result && (
        <div className="mt-2 text-xs text-terminal-text bg-terminal-bg border border-terminal-border rounded p-2">
          <div>
            <span className="text-terminal-bear">Bear case:</span> {result.bear_case}
          </div>
          <div className="mt-1">
            <span className="text-terminal-warn">Skeptic:</span> {result.skeptic_case}
          </div>
          {result.unresolved_questions.length > 0 && (
            <div className="mt-1 text-terminal-muted">
              Unresolved: {result.unresolved_questions.join("; ")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
