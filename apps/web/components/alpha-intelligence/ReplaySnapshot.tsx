"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface TimeSeriesObservation {
  id: string;
  series_id: string;
  category: string;
  value: number;
  unit: string;
  observation_time: string;
  publication_time: string;
}

interface Signal {
  id: string;
  signal_type: string;
  headline: string;
  materiality_score: number;
  detected_at: string;
}

interface ImpactAnalysis {
  id: string;
  event_type: string;
  physical_impact: string;
  curve_implications: string;
}

interface ConsensusView {
  id: string;
  consensus_type: string;
  market: string;
  target: string;
  agreement_label: string;
  agent_count: number;
}

interface ScenarioRunResult {
  id: string;
  scenario_name: string;
  portfolio_pnl: number;
  var_impact: number;
  run_at: string;
}

interface MemoryRecord {
  id: string;
  title: string;
  outcome_quadrant: string | null;
  created_at: string;
}

interface AsOfReplayResult {
  market: string;
  as_of: string;
  mode: string;
  price_observations: TimeSeriesObservation[];
  signals: Signal[];
  impacts: ImpactAnalysis[];
  consensus_views: ConsensusView[];
  scenario_runs: ScenarioRunResult[];
  memory_records: MemoryRecord[];
  generated_at: string;
}

function toLocalInputValue(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function Section<T extends { id: string }>({
  title,
  rows,
  empty,
  render,
}: {
  title: string;
  rows: T[];
  empty: string;
  render: (row: T) => React.ReactNode;
}) {
  return (
    <div className="panel">
      <div className="panel-title">
        {title} <span className="text-terminal-muted">({rows.length})</span>
      </div>
      {rows.length === 0 ? (
        <div className="text-[11px] text-terminal-muted">{empty}</div>
      ) : (
        <table className="mono-table w-full">
          <tbody>{rows.map((row) => render(row))}</tbody>
        </table>
      )}
    </div>
  );
}

export function ReplaySnapshot() {
  const { token } = useAuth();
  const [asOfInput, setAsOfInput] = useState(() => toLocalInputValue(new Date().toISOString()));
  const [result, setResult] = useState<AsOfReplayResult | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(
    async (asOfIso: string) => {
      if (!token) return;
      setLoading(true);
      setMessage(null);
      try {
        const data = await apiGet<AsOfReplayResult>(
          `/alpha/replay?as_of=${encodeURIComponent(asOfIso)}`,
          token
        );
        setResult(data);
      } catch {
        setMessage("Unable to load AlphaReplay data — this requires the 'alpha_replay.view' permission.");
      } finally {
        setLoading(false);
      }
    },
    [token]
  );

  useEffect(() => {
    load(new Date().toISOString());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  function handleLoadClick() {
    load(new Date(asOfInput).toISOString());
  }

  function handleNowClick() {
    const nowIso = new Date().toISOString();
    setAsOfInput(toLocalInputValue(nowIso));
    load(nowIso);
  }

  return (
    <div className="space-y-4">
      <h1 className="panel-title">AlphaReplay™ — Market Time Machine</h1>
      <p className="text-[11px] text-terminal-muted">
        Reconstructs what the Alpha Intelligence Layer itself knew and concluded as of a chosen
        moment, bitemporally filtered so nothing recorded after that moment leaks in. Honest about
        scope: this is always a <span className="text-terminal-accent">CURRENT_MODEL_RETROSPECTIVE</span> —
        a replay of what this already-running system recorded at the time, not a reconstruction of
        market reality from before AlphaReplay&apos;s bitemporal store existed. An <code>as_of</code>{" "}
        before then simply returns empty lists rather than fabricating a plausible-looking history.
      </p>

      <div className="panel flex flex-wrap items-end gap-3">
        <label className="flex flex-col text-[10px] text-terminal-muted gap-1">
          As of
          <input
            type="datetime-local"
            value={asOfInput}
            onChange={(e) => setAsOfInput(e.target.value)}
            className="bg-terminal-bg border border-terminal-border rounded px-2 py-1 text-xs text-terminal-text"
          />
        </label>
        <button
          onClick={handleLoadClick}
          disabled={loading}
          className="text-[11px] px-2 py-1 border border-terminal-border rounded hover:border-terminal-accent disabled:opacity-50"
        >
          Load snapshot
        </button>
        <button
          onClick={handleNowClick}
          disabled={loading}
          className="text-[11px] px-2 py-1 border border-terminal-border rounded hover:border-terminal-accent disabled:opacity-50"
        >
          Now
        </button>
        {result && (
          <span className="text-[10px] text-terminal-muted">
            mode: <span className="text-terminal-accent">{result.mode}</span> · generated{" "}
            {new Date(result.generated_at).toLocaleString()}
          </span>
        )}
      </div>

      {message && <p className="text-xs text-terminal-bear">{message}</p>}
      {loading && <p className="text-xs text-terminal-muted">Loading…</p>}

      {result && !loading && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Section
            title="Price observations"
            rows={result.price_observations}
            empty="No price observations recorded as of this moment."
            render={(o) => (
              <tr key={o.id}>
                <td className="whitespace-nowrap">{o.series_id}</td>
                <td>
                  {o.value} {o.unit}
                </td>
                <td className="text-terminal-muted whitespace-nowrap">
                  {new Date(o.observation_time).toLocaleString()}
                </td>
              </tr>
            )}
          />
          <Section
            title="Signals"
            rows={result.signals}
            empty="No signals recorded as of this moment."
            render={(s) => (
              <tr key={s.id}>
                <td className="whitespace-nowrap">{s.signal_type}</td>
                <td className="break-words">{s.headline}</td>
                <td className="text-terminal-muted whitespace-nowrap">{s.materiality_score.toFixed(0)}</td>
              </tr>
            )}
          />
          <Section
            title="Impact analyses"
            rows={result.impacts}
            empty="No impact analyses recorded as of this moment."
            render={(i) => (
              <tr key={i.id}>
                <td className="whitespace-nowrap">{i.event_type}</td>
                <td className="break-words">{i.physical_impact}</td>
                <td className="text-terminal-muted break-words">{i.curve_implications}</td>
              </tr>
            )}
          />
          <Section
            title="Consensus views"
            rows={result.consensus_views}
            empty="No consensus views recorded as of this moment."
            render={(c) => (
              <tr key={c.id}>
                <td className="whitespace-nowrap">
                  {c.market} / {c.target}
                </td>
                <td>{c.agreement_label}</td>
                <td className="text-terminal-muted whitespace-nowrap">{c.agent_count} agents</td>
              </tr>
            )}
          />
          <Section
            title="Scenario runs"
            rows={result.scenario_runs}
            empty="No scenario runs recorded as of this moment."
            render={(r) => (
              <tr key={r.id}>
                <td className="whitespace-nowrap">{r.scenario_name}</td>
                <td>{r.portfolio_pnl.toFixed(2)}</td>
                <td className="text-terminal-muted whitespace-nowrap">VaR {r.var_impact.toFixed(2)}</td>
              </tr>
            )}
          />
          <Section
            title="Decision memory"
            rows={result.memory_records}
            empty="No decision memory recorded as of this moment."
            render={(m) => (
              <tr key={m.id}>
                <td className="break-words">{m.title}</td>
                <td className="text-terminal-muted whitespace-nowrap">{m.outcome_quadrant ?? "—"}</td>
                <td className="text-terminal-muted whitespace-nowrap">
                  {new Date(m.created_at).toLocaleDateString()}
                </td>
              </tr>
            )}
          />
        </div>
      )}
    </div>
  );
}
