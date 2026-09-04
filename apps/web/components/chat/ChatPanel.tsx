"use client";

import { useState } from "react";
import { apiPost } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  citations?: { source: string; reference: string }[];
  created_at?: string;
}

const SUGGESTIONS = [
  "Why are we bullish natural gas?",
  "What are the three strongest arguments against this trade?",
  "What changed in the last six hours?",
  "Compare our EIA forecast to market consensus.",
  "Show the five largest risks in the portfolio.",
];

export function ChatPanel() {
  const { token } = useAuth();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  async function ensureSession(): Promise<string> {
    if (sessionId) return sessionId;
    const session = await apiPost<{ id: string }>("/chat/sessions", undefined, token ?? undefined);
    setSessionId(session.id);
    return session.id;
  }

  async function send(content: string) {
    if (!content.trim()) return;
    // Chief Trading Agent Chat requires the `chief_agent.chat` permission
    // (docs/access-model.md §6, spec §26) -- enforced server-side regardless, but
    // failing fast here avoids a confusing generic error for a signed-out visitor.
    if (!token) {
      setMessages((prev) => [
        ...prev,
        { role: "user", content },
        { role: "assistant", content: "Sign in to an entitled account to use the Chief Trading Agent Chat." },
      ]);
      setInput("");
      return;
    }
    setLoading(true);
    setMessages((prev) => [...prev, { role: "user", content }]);
    setInput("");
    try {
      const id = await ensureSession();
      const reply = await apiPost<ChatMessage>(`/chat/sessions/${id}/messages`, { content }, token);
      setMessages((prev) => [...prev, reply]);
    } catch (err) {
      const status = err instanceof Error ? err.message : "";
      const content =
        status.includes("403") || status.includes("401")
          ? "Your account isn't entitled to the Chief Trading Agent Chat. Contact your administrator if you believe this is incorrect."
          : "Unable to reach the AI Trader Chat backend right now.";
      setMessages((prev) => [...prev, { role: "assistant", content }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="panel flex flex-col h-[480px]">
      <div className="panel-title">AI Trader Chat</div>
      <div className="flex-1 overflow-y-auto space-y-2 text-sm">
        {messages.length === 0 && (
          <div className="flex flex-wrap gap-1">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => send(s)}
                className="text-[11px] px-2 py-1 border border-terminal-border rounded text-terminal-muted hover:text-terminal-text hover:border-terminal-accent"
              >
                {s}
              </button>
            ))}
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "text-terminal-text" : "text-terminal-accent"}>
            <span className="text-[10px] text-terminal-muted mr-1">{m.role === "user" ? "you" : "alphagasiq"}</span>
            <span className="whitespace-pre-wrap">{m.content}</span>
          </div>
        ))}
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="mt-2 flex gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about the market, a trade, or the portfolio..."
          className="flex-1 bg-terminal-bg border border-terminal-border rounded px-2 py-1 text-sm text-terminal-text focus:outline-none focus:border-terminal-accent"
        />
        <button
          type="submit"
          disabled={loading}
          className="text-xs px-3 py-1 border border-terminal-accent text-terminal-accent rounded hover:bg-terminal-accent/10 disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </div>
  );
}
