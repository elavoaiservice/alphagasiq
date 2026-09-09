"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

type CommitType =
  | "feat" | "fix" | "docs" | "refactor" | "perf"
  | "test" | "chore" | "style" | "build" | "ci" | "revert" | "other";

interface Commit {
  sha: string;
  short_sha: string;
  type: CommitType;
  scope: string | null;
  summary: string;
  subject: string;
  body: string;
  breaking: boolean;
  committed_at: string;
  deployed_at: string | null;
  deploy_pending: boolean;
  author?: string | null;
}

interface DayGroup { date: string; label: string; commits: Commit[] }

interface ChangelogResponse {
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
  scanned: number;
  history_available: boolean;
  running_sha: string | null;
  branch: string;
  latest_deploy: { commit_sha: string; deployed_at: string } | null;
  groups: DayGroup[];
}

const PAGE = 50;

/** type -> badge styling + emoji. Mirrors COMMIT_TYPE_META in api_app/changelog.py. */
const TYPE_STYLE: Record<CommitType, { label: string; emoji: string; cls: string }> = {
  feat:     { label: "Feature",  emoji: "✨", cls: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  fix:      { label: "Fix",      emoji: "\u{1F41B}", cls: "bg-rose-50 text-rose-700 ring-rose-200" },
  perf:     { label: "Perf",     emoji: "⚡", cls: "bg-amber-50 text-amber-700 ring-amber-200" },
  refactor: { label: "Refactor", emoji: "♻️", cls: "bg-sky-50 text-sky-700 ring-sky-200" },
  docs:     { label: "Docs",     emoji: "\u{1F4DD}", cls: "bg-violet-50 text-violet-700 ring-violet-200" },
  test:     { label: "Tests",    emoji: "\u{1F9EA}", cls: "bg-teal-50 text-teal-700 ring-teal-200" },
  build:    { label: "Build",    emoji: "\u{1F4E6}", cls: "bg-stone-100 text-stone-600 ring-stone-200" },
  ci:       { label: "CI",       emoji: "\u{1F527}", cls: "bg-stone-100 text-stone-600 ring-stone-200" },
  style:    { label: "Style",    emoji: "\u{1F485}", cls: "bg-pink-50 text-pink-700 ring-pink-200" },
  chore:    { label: "Chore",    emoji: "\u{1F9F9}", cls: "bg-gray-100 text-gray-600 ring-gray-200" },
  revert:   { label: "Revert",   emoji: "⏪", cls: "bg-red-50 text-red-700 ring-red-200" },
  other:    { label: "Other",    emoji: "•", cls: "bg-gray-100 text-gray-500 ring-gray-200" },
};

const CT = "America/Chicago";
function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("en-US", {
    timeZone: CT, month: "short", day: "numeric", year: "numeric",
    hour: "numeric", minute: "2-digit",
  }).format(d) + " CT";
}
function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("en-US", {
    timeZone: CT, hour: "numeric", minute: "2-digit",
  }).format(d) + " CT";
}

export default function ChangelogPage() {
  const { token } = useAuth();
  const [groups, setGroups] = useState<DayGroup[]>([]);
  const [meta, setMeta] = useState<Omit<ChangelogResponse, "groups"> | null>(null);
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const reqId = useRef(0);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 300);
    return () => clearTimeout(t);
  }, [query]);

  const fetchPage = useCallback(async (q: string, offset: number) => {
    if (!token) return;
    const mine = ++reqId.current;
    if (offset === 0) setLoading(true); else setLoadingMore(true);
    setError("");
    try {
      const params = new URLSearchParams({ q, offset: String(offset), limit: String(PAGE) });
      const data = await apiGet<ChangelogResponse>(`/admin/changelog?${params}`, token);
      if (mine !== reqId.current) return; // a newer request superseded this one
      const { groups: pageGroups, ...rest } = data;
      setMeta(rest);
      setGroups((prev) => {
        if (offset === 0) return pageGroups;
        // Merge the boundary day so a date split across pages stays one block.
        const next = prev.map((g) => ({ ...g, commits: [...g.commits] }));
        for (const g of pageGroups) {
          const last = next[next.length - 1];
          if (last && last.date === g.date) last.commits.push(...g.commits);
          else next.push(g);
        }
        return next;
      });
    } catch {
      if (mine === reqId.current) setError("Could not load the changelog.");
    } finally {
      if (mine === reqId.current) { setLoading(false); setLoadingMore(false); }
    }
  }, [token]);

  useEffect(() => { fetchPage(debounced, 0); }, [debounced, fetchPage]);

  const shownCount = groups.reduce((n, g) => n + g.commits.length, 0);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-sm font-semibold">Changelog</h1>
          <p className="mt-0.5 text-xs text-terminal-muted">
            Every change shipped to the platform, newest first. Search a keyword (e.g. &ldquo;storage&rdquo;)
            to see every related update and when it went live.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search updates…"
              className="w-64 rounded-lg border border-terminal-border bg-terminal-panel py-2 pl-3 pr-8 text-xs text-terminal-text placeholder-terminal-muted focus:border-elavo-blue focus:outline-none"
            />
            {query && (
              <button
                onClick={() => setQuery("")}
                title="Clear"
                className="absolute right-2 top-1/2 -translate-y-1/2 text-terminal-muted hover:text-terminal-text">
                ✕
              </button>
            )}
          </div>
          <button
            onClick={() => fetchPage(debounced, 0)}
            disabled={loading}
            title="Refresh"
            className="rounded-lg border border-terminal-border bg-terminal-panel px-3 py-2 text-xs font-medium text-terminal-text hover:bg-elavo-skyTint disabled:opacity-50">
            {loading ? "…" : "↻"}
          </button>
        </div>
      </div>

      {/* Status strip */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-terminal-muted">
        {meta && (
          <span>
            {debounced
              ? <><strong className="text-terminal-text">{meta.total}</strong> match{meta.total === 1 ? "" : "es"} for &ldquo;{debounced}&rdquo;</>
              : <><strong className="text-terminal-text">{meta.total.toLocaleString()}</strong> updates</>}
          </span>
        )}
        {meta?.latest_deploy && (
          <span className="text-terminal-bull">Last deploy: {fmtDateTime(meta.latest_deploy.deployed_at)}</span>
        )}
        {meta && <span>branch <code className="font-mono">{meta.branch}</code></span>}
      </div>

      {meta && !meta.history_available && (
        <div className="panel text-xs text-terminal-warn">
          This build has no baked commit history (<code>/app/changelog.json</code> is missing —
          normal for a local <code>uvicorn --reload</code> run). The feed will populate after the
          next Docker build.
        </div>
      )}

      {error && <div className="panel text-xs text-terminal-bear">{error}</div>}

      {loading ? (
        <div className="panel p-12 text-center text-xs text-terminal-muted">Loading…</div>
      ) : groups.length === 0 ? (
        <div className="panel p-12 text-center text-xs text-terminal-muted">
          {debounced ? `No updates match “${debounced}”.` : "No updates found."}
        </div>
      ) : (
        <div className="space-y-6">
          {groups.map((group) => (
            <div key={group.date}>
              <div className="sticky top-0 z-10 -mx-1 mb-2 bg-terminal-bg/90 px-1 py-1 backdrop-blur">
                <h3 className="text-xs font-semibold text-terminal-text">{group.label}</h3>
              </div>
              <div className="space-y-2">
                {group.commits.map((c) => <CommitRow key={c.sha} c={c} />)}
              </div>
            </div>
          ))}

          {meta?.has_more && (
            <div className="flex justify-center pt-2">
              <button
                onClick={() => fetchPage(debounced, shownCount)}
                disabled={loadingMore}
                className="rounded-lg border border-terminal-border bg-terminal-panel px-4 py-2 text-xs font-medium text-terminal-text hover:bg-elavo-skyTint disabled:opacity-50">
                {loadingMore ? "Loading…" : "Load more"}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function CommitRow({ c }: { c: Commit }) {
  const [open, setOpen] = useState(false);
  const style = TYPE_STYLE[c.type] ?? TYPE_STYLE.other;
  const hasBody = c.body.trim().length > 0;

  return (
    <div className="rounded-xl border border-terminal-border bg-terminal-panel px-4 py-3">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ring-1 ${style.cls}`}>
              <span>{style.emoji}</span>{style.label}
            </span>
            {c.scope && (
              <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-medium text-gray-600 ring-1 ring-gray-200">
                {c.scope}
              </span>
            )}
            {c.breaking && (
              <span className="rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-bold text-red-700 ring-1 ring-red-300">
                BREAKING
              </span>
            )}
          </div>
          <p className="mt-1.5 text-xs text-terminal-text">{c.summary}</p>
          {hasBody && (
            <button
              onClick={() => setOpen((o) => !o)}
              className="mt-1 text-[11px] font-medium text-elavo-blueDark hover:text-elavo-blueDeep">
              {open ? "▲ Hide details" : "▼ Details"}
            </button>
          )}
          {open && hasBody && (
            <pre className="mt-2 whitespace-pre-wrap rounded-lg bg-terminal-bg p-3 font-sans text-[11px] leading-relaxed text-terminal-muted ring-1 ring-terminal-border">
              {c.body}
            </pre>
          )}
        </div>

        <div className="flex flex-shrink-0 flex-col items-end gap-1 text-right">
          {c.deployed_at ? (
            <span className="text-[11px] font-medium text-terminal-bull" title="Went live on this deployment">
              {fmtTime(c.deployed_at)}
            </span>
          ) : c.deploy_pending ? (
            <span
              className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700 ring-1 ring-amber-200"
              title="Pushed but not running here yet — an upgrade will bring it in">
              Not deployed
            </span>
          ) : (
            <span className="text-[11px] text-terminal-muted" title="Deploy time not recorded — showing commit time">
              {fmtTime(c.committed_at)}
            </span>
          )}
          <span className="font-mono text-[10px] text-terminal-muted/60">{c.short_sha}</span>
        </div>
      </div>
    </div>
  );
}
