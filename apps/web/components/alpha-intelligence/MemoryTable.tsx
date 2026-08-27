"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface MemoryRecord {
  id: string;
  memory_type: string;
  trade_id: string | null;
  market: string;
  strategy: string;
  title: string;
  summary: string;
  outcome_quadrant: string | null;
  structured_context: Record<string, unknown>;
  tags: string[];
  created_at: string;
}

interface LessonProposal {
  id: string;
  memory_record_id: string;
  proposed_lesson: string;
  rationale: string;
  status: "PENDING" | "APPROVED" | "REJECTED";
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
}

const QUADRANT_COLOR: Record<string, string> = {
  GOOD_DECISION_GOOD_OUTCOME: "text-terminal-bull",
  GOOD_DECISION_BAD_OUTCOME: "text-terminal-warn",
  BAD_DECISION_GOOD_OUTCOME: "text-terminal-warn",
  BAD_DECISION_BAD_OUTCOME: "text-terminal-bear",
};

function MemoryDetail({ memory }: { memory: MemoryRecord }) {
  return (
    <div className="panel">
      <div className="panel-title">
        {memory.title}{" "}
        {memory.outcome_quadrant && (
          <span className={QUADRANT_COLOR[memory.outcome_quadrant] ?? ""}>({memory.outcome_quadrant})</span>
        )}
      </div>
      <div className="text-xs mb-2">{memory.summary}</div>
      <div className="text-[10px] text-terminal-muted mb-2">
        {memory.market} · {memory.strategy} · {memory.memory_type}
      </div>
      <table className="mono-table w-full">
        <tbody>
          {Object.entries(memory.structured_context).map(([key, value]) => (
            <tr key={key}>
              <td className="text-terminal-muted whitespace-nowrap">{key}</td>
              <td className="break-all">{typeof value === "object" ? JSON.stringify(value) : String(value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function MemoryTable() {
  const { token } = useAuth();
  const [memories, setMemories] = useState<MemoryRecord[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [lessons, setLessons] = useState<LessonProposal[] | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [reviewMessage, setReviewMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    apiGet<MemoryRecord[]>("/alpha/memory", token)
      .then(setMemories)
      .catch(() => setMessage("Unable to load AlphaMemory data — this requires the 'alpha_memory.view' permission."));
    apiGet<LessonProposal[]>("/alpha/memory/lessons", token).then(setLessons).catch(() => {});
  }, [token]);

  async function reviewLesson(lessonId: string, status: "APPROVED" | "REJECTED") {
    if (!token) return;
    setReviewMessage(null);
    try {
      const updated = await apiPost<LessonProposal>(`/alpha/memory/lessons/${lessonId}/review`, { status }, token);
      setLessons((prev) => (prev ? prev.map((l) => (l.id === updated.id ? updated : l)) : prev));
    } catch {
      setReviewMessage("Unable to review lesson — this requires the 'alpha_memory.review' permission.");
    }
  }

  if (message && !memories) return <p className="text-xs text-terminal-bear">{message}</p>;
  if (!memories) return <p className="text-xs text-terminal-muted">Loading…</p>;

  const activeMemory = memories.find((m) => m.id === selected) ?? memories[0] ?? null;

  return (
    <div className="space-y-4">
      <h1 className="panel-title">AlphaMemory™ — Institutional Decision Memory</h1>
      <p className="text-[11px] text-terminal-muted">
        A durable record of every closed trade&apos;s decision quality vs. outcome quality, and the
        deterministic, template-drafted lesson proposals derived from each outcome quadrant — always
        human-reviewed before they could ever influence a production model or threshold.
      </p>
      {message && <p className="text-xs text-terminal-bear">{message}</p>}

      {memories.length === 0 ? (
        <div className="panel">
          <div className="text-xs text-terminal-muted">No decision memory yet — close a paper trade to generate one.</div>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="panel overflow-x-auto lg:col-span-1">
            <table className="mono-table w-full">
              <thead>
                <tr>
                  <th>Trade</th>
                  <th>Outcome</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {memories.map((m) => (
                  <tr key={m.id} className={m.id === activeMemory?.id ? "text-terminal-accent" : ""}>
                    <td className="whitespace-nowrap">
                      {m.strategy} / {m.market}
                    </td>
                    <td className={m.outcome_quadrant ? QUADRANT_COLOR[m.outcome_quadrant] ?? "" : ""}>
                      {m.outcome_quadrant ?? "—"}
                    </td>
                    <td>
                      <button
                        onClick={() => setSelected(m.id)}
                        className="text-[10px] px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-accent"
                      >
                        View
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="lg:col-span-2">{activeMemory && <MemoryDetail memory={activeMemory} />}</div>
        </div>
      )}

      {lessons && lessons.length > 0 && (
        <div className="panel">
          <div className="panel-title">Lesson proposals</div>
          {reviewMessage && <p className="text-xs text-terminal-bear mb-2">{reviewMessage}</p>}
          <div className="flex flex-col gap-3">
            {lessons.map((lesson) => (
              <div key={lesson.id} className="border border-terminal-border rounded p-2">
                <div className="text-xs mb-1">{lesson.proposed_lesson}</div>
                <div className="text-[10px] text-terminal-muted mb-2">{lesson.rationale}</div>
                <div className="flex items-center gap-2 text-[10px]">
                  <span
                    className={
                      lesson.status === "APPROVED"
                        ? "text-terminal-bull"
                        : lesson.status === "REJECTED"
                          ? "text-terminal-bear"
                          : "text-terminal-muted"
                    }
                  >
                    {lesson.status}
                  </span>
                  {lesson.status === "PENDING" && (
                    <>
                      <button
                        onClick={() => reviewLesson(lesson.id, "APPROVED")}
                        className="px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-bull hover:text-terminal-bull"
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => reviewLesson(lesson.id, "REJECTED")}
                        className="px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-bear hover:text-terminal-bear"
                      >
                        Reject
                      </button>
                    </>
                  )}
                  {lesson.reviewed_by && <span>reviewed by {lesson.reviewed_by}</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
