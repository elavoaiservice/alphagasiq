"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface LibraryScenario {
  scenario_id: string;
  name: string;
  description: string;
  price_shock_pct: number;
  demand_shock_bcf_d: number;
  supply_shock_bcf_d: number;
  volatility_multiplier: number;
}

interface ScenarioRunResult {
  id: string;
  scenario_name: string;
  scenario_description: string;
  base_scenario_ids: string[];
  price_shock_pct: number;
  demand_shock_bcf_d: number;
  supply_shock_bcf_d: number;
  volatility_multiplier: number;
  portfolio_pnl: number;
  strategy_pnl: Record<string, number>;
  margin_impact: number;
  var_impact: number;
  largest_risk_contributor: string;
  run_at: string;
}

interface ScenarioComparison {
  worst_case_scenario_name: string;
  worst_case_portfolio_pnl: number;
  best_case_scenario_name: string;
  best_case_portfolio_pnl: number;
  ranked_scenario_names: string[];
}

function PnlBadge({ value }: { value: number }) {
  return <span className={value >= 0 ? "text-terminal-bull" : "text-terminal-bear"}>{value >= 0 ? "+" : ""}{value.toFixed(2)}</span>;
}

export function ScenarioRunner() {
  const { token } = useAuth();
  const [library, setLibrary] = useState<LibraryScenario[] | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [customPct, setCustomPct] = useState<string>("");
  const [lastRun, setLastRun] = useState<ScenarioRunResult | null>(null);
  const [history, setHistory] = useState<ScenarioRunResult[] | null>(null);
  const [comparison, setComparison] = useState<{ results: ScenarioRunResult[]; comparison: ScenarioComparison } | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!token) return;
    apiGet<LibraryScenario[]>("/alpha/scenarios/library", token)
      .then((lib) => {
        setLibrary(lib);
        setSelectedId((prev) => prev ?? lib[0]?.scenario_id ?? null);
      })
      .catch(() => setMessage("Unable to load the scenario library — this requires the 'alpha_scenarios.view' permission."));
    apiGet<ScenarioRunResult[]>("/alpha/scenarios/runs?since_hours=24", token).then(setHistory).catch(() => {});
  }, [token]);

  async function runSelected() {
    if (!token || !selectedId) return;
    setBusy(true);
    setMessage(null);
    try {
      const variables = customPct.trim()
        ? [{ factor_type: "PRICE_SHOCK_PCT", value: parseFloat(customPct) / 100 }]
        : [];
      const scenario = library?.find((s) => s.scenario_id === selectedId);
      const result = await apiPost<ScenarioRunResult>(
        "/alpha/scenarios/run",
        { name: scenario?.name ?? selectedId, base_scenario_ids: [selectedId], variables },
        token
      );
      setLastRun(result);
      setHistory((prev) => [result, ...(prev ?? [])].slice(0, 50));
    } catch {
      setMessage("Unable to run scenario — this requires the 'alpha_scenarios.run' permission.");
    } finally {
      setBusy(false);
    }
  }

  async function runComparison() {
    if (!token) return;
    setBusy(true);
    setMessage(null);
    try {
      const result = await apiPost<{ results: ScenarioRunResult[]; comparison: ScenarioComparison }>(
        "/alpha/scenarios/compare",
        {},
        token
      );
      setComparison(result);
      setHistory((prev) => [...result.results, ...(prev ?? [])].slice(0, 50));
    } catch {
      setMessage("Unable to run the standing library comparison — this requires the 'alpha_scenarios.run' permission.");
    } finally {
      setBusy(false);
    }
  }

  if (message && !library) return <p className="text-xs text-terminal-bear">{message}</p>;
  if (!library) return <p className="text-xs text-terminal-muted">Loading…</p>;

  return (
    <div className="space-y-4">
      <h1 className="panel-title">AlphaScenario™ — Counterfactual Stress Testing</h1>
      <p className="text-[11px] text-terminal-muted">
        Composes named base scenarios from the standing stress-test library with an optional custom price
        shock, then runs the combined shock against the current paper book — reusing the same P&amp;L/VaR
        math the Risk Governor's scenario engine already uses, not a separate calculation.
      </p>
      {message && <p className="text-xs text-terminal-bear">{message}</p>}

      <div className="panel">
        <div className="panel-title">Run a scenario</div>
        <div className="flex flex-wrap items-end gap-3 text-xs">
          <label className="flex flex-col gap-1">
            <span className="text-terminal-muted text-[10px]">Base scenario</span>
            <select
              className="bg-transparent border border-terminal-border rounded px-2 py-1"
              value={selectedId ?? ""}
              onChange={(e) => setSelectedId(e.target.value)}
            >
              {library.map((s) => (
                <option key={s.scenario_id} value={s.scenario_id}>
                  {s.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-terminal-muted text-[10px]">+ custom price shock (%, optional)</span>
            <input
              className="bg-transparent border border-terminal-border rounded px-2 py-1 w-28"
              placeholder="e.g. 20 or -15"
              value={customPct}
              onChange={(e) => setCustomPct(e.target.value)}
            />
          </label>
          <button
            onClick={runSelected}
            disabled={busy || !selectedId}
            className="text-[10px] px-2 py-1 border border-terminal-border rounded hover:border-terminal-accent disabled:opacity-50"
          >
            Run scenario
          </button>
          <button
            onClick={runComparison}
            disabled={busy}
            className="text-[10px] px-2 py-1 border border-terminal-border rounded hover:border-terminal-accent disabled:opacity-50"
          >
            Run entire standing library
          </button>
        </div>
        {selectedId && (
          <div className="text-[10px] text-terminal-muted mt-2">
            {library.find((s) => s.scenario_id === selectedId)?.description}
          </div>
        )}
      </div>

      {lastRun && (
        <div className="panel">
          <div className="panel-title">{lastRun.scenario_name}</div>
          <div className="text-xs">
            Portfolio P&amp;L: <PnlBadge value={lastRun.portfolio_pnl} /> · VaR impact {lastRun.var_impact.toFixed(2)} ·
            Margin impact {lastRun.margin_impact.toFixed(2)} · Largest risk contributor: {lastRun.largest_risk_contributor}
          </div>
          <div className="text-[10px] text-terminal-muted mt-1">
            Composed shock: price {lastRun.price_shock_pct >= 0 ? "+" : ""}
            {(lastRun.price_shock_pct * 100).toFixed(0)}%, demand {lastRun.demand_shock_bcf_d.toFixed(1)} Bcf/d, supply{" "}
            {lastRun.supply_shock_bcf_d.toFixed(1)} Bcf/d, volatility ×{lastRun.volatility_multiplier.toFixed(2)}
          </div>
        </div>
      )}

      {comparison && (
        <div className="panel">
          <div className="panel-title">Standing library comparison ({comparison.results.length} scenarios)</div>
          <div className="text-xs mb-2">
            Worst case: <strong>{comparison.comparison.worst_case_scenario_name}</strong>{" "}
            <PnlBadge value={comparison.comparison.worst_case_portfolio_pnl} /> · Best case:{" "}
            <strong>{comparison.comparison.best_case_scenario_name}</strong>{" "}
            <PnlBadge value={comparison.comparison.best_case_portfolio_pnl} />
          </div>
          <table className="mono-table w-full">
            <thead>
              <tr>
                <th>Scenario</th>
                <th>Portfolio P&amp;L</th>
                <th>VaR impact</th>
              </tr>
            </thead>
            <tbody>
              {comparison.results
                .slice()
                .sort((a, b) => a.portfolio_pnl - b.portfolio_pnl)
                .map((r) => (
                  <tr key={r.id}>
                    <td className="whitespace-nowrap">{r.scenario_name}</td>
                    <td>
                      <PnlBadge value={r.portfolio_pnl} />
                    </td>
                    <td>{r.var_impact.toFixed(2)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}

      {history && history.length > 0 && (
        <div className="panel">
          <div className="panel-title">Recent runs</div>
          <table className="mono-table w-full">
            <thead>
              <tr>
                <th>Scenario</th>
                <th>Portfolio P&amp;L</th>
                <th>Run at</th>
              </tr>
            </thead>
            <tbody>
              {history.slice(0, 15).map((r) => (
                <tr key={r.id}>
                  <td className="whitespace-nowrap">{r.scenario_name}</td>
                  <td>
                    <PnlBadge value={r.portfolio_pnl} />
                  </td>
                  <td className="text-[10px] text-terminal-muted">{new Date(r.run_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
