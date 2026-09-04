import { apiGet } from "@/lib/api-client";

interface StrategyStats {
  count: number;
  wins: number;
  avg_thesis_accuracy: number;
  win_rate: number;
}

interface BacktestedModelStats {
  n_folds: number;
  directional_accuracy: number;
  mae: number;
  rmse: number;
  sharpe_ratio: number | null;
}

interface LiveModelStats {
  n: number;
  directional_accuracy: number;
  brier_score: number | null;
}

interface QuantSection {
  backtested: Record<string, BacktestedModelStats>;
  live: {
    n_forecasts_resolved: number;
    directional_accuracy: number | null;
    brier_score: number | null;
    by_model: Record<string, LiveModelStats>;
  };
}

interface PerformanceSummary {
  closed_trade_count: number;
  win_rate: number | null;
  avg_thesis_accuracy: number | null;
  avg_timing_accuracy: number | null;
  avg_risk_accuracy: number | null;
  by_quadrant: Record<string, number>;
  by_strategy: Record<string, StrategyStats>;
  quant: QuantSection;
  classification: string;
}

const QUADRANT_LABELS: Record<string, string> = {
  GOOD_DECISION_GOOD_OUTCOME: "Good decision / good outcome",
  GOOD_DECISION_BAD_OUTCOME: "Good decision / bad outcome",
  BAD_DECISION_GOOD_OUTCOME: "Bad decision / good outcome",
  BAD_DECISION_BAD_OUTCOME: "Bad decision / bad outcome",
};

function pct(value: number | null | undefined): string {
  return value == null ? "—" : `${(value * 100).toFixed(0)}%`;
}

function QuantBacktestedVsLive({ quant }: { quant: QuantSection }) {
  const modelNames = Array.from(
    new Set([...Object.keys(quant.backtested), ...Object.keys(quant.live.by_model)])
  );

  return (
    <div className="panel">
      <div className="panel-title">Quantitative Models — Backtested vs. Live</div>
      <div className="text-[10px] text-terminal-muted mb-2">
        Backtested = walk-forward validation over historical price history (services/quant). Live = this
        model&apos;s actual forecasts on trades that have since closed. Both use the same directional-accuracy
        metric, so they are directly comparable — a model that backtests well but performs worse live is a
        real, visible signal here, not hidden.
      </div>
      <table className="mono-table">
        <thead>
          <tr>
            <th>Model</th>
            <th>Backtested dir. acc.</th>
            <th>Backtested folds</th>
            <th>Live dir. acc.</th>
            <th>Live n</th>
            <th>Live Brier</th>
          </tr>
        </thead>
        <tbody>
          {modelNames.map((name) => {
            const bt = quant.backtested[name];
            const live = quant.live.by_model[name];
            return (
              <tr key={name}>
                <td>{name}</td>
                <td>{pct(bt?.directional_accuracy)}</td>
                <td>{bt?.n_folds ?? "—"}</td>
                <td className={live && bt && live.directional_accuracy < bt.directional_accuracy ? "text-terminal-warn" : ""}>
                  {pct(live?.directional_accuracy)}
                </td>
                <td>{live?.n ?? "—"}</td>
                <td>{live?.brier_score ?? "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export async function ModelPerformanceTable() {
  const summary = await apiGet<PerformanceSummary>("/models/performance").catch(() => null);

  if (!summary) {
    return (
      <div className="panel">
        <div className="panel-title">Model Performance</div>
        <div className="text-xs text-terminal-warn">Unable to reach the model-performance endpoint.</div>
      </div>
    );
  }

  if (summary.closed_trade_count === 0) {
    return (
      <div className="flex flex-col gap-4">
        <QuantBacktestedVsLive quant={summary.quant} />
        <div className="panel">
          <div className="panel-title">Post-Trade Learning</div>
          <div className="text-xs text-terminal-muted">
            No trades have closed yet. Approve a recommendation and close the resulting position (see the
            dashboard&apos;s Approval Queue and Paper Positions panels) to start building a live performance
            record.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="panel">
        <div className="panel-title">Overall — {summary.closed_trade_count} closed trade(s)</div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm font-mono">
          <div>
            <div className="text-[10px] text-terminal-muted">Win rate</div>
            {pct(summary.win_rate)}
          </div>
          <div>
            <div className="text-[10px] text-terminal-muted">Avg thesis accuracy</div>
            {pct(summary.avg_thesis_accuracy)}
          </div>
          <div>
            <div className="text-[10px] text-terminal-muted">Avg timing accuracy</div>
            {pct(summary.avg_timing_accuracy)}
          </div>
          <div>
            <div className="text-[10px] text-terminal-muted">Avg risk accuracy</div>
            {pct(summary.avg_risk_accuracy)}
          </div>
        </div>
      </div>

      <QuantBacktestedVsLive quant={summary.quant} />

      <div className="panel">
        <div className="panel-title">Decision vs. Outcome Quadrant</div>
        <table className="mono-table">
          <tbody>
            {Object.entries(summary.by_quadrant).map(([quadrant, count]) => (
              <tr key={quadrant}>
                <td>{QUADRANT_LABELS[quadrant] ?? quadrant}</td>
                <td className="text-right">{count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <div className="panel-title">By Strategy</div>
        <table className="mono-table">
          <thead>
            <tr>
              <th>Strategy</th>
              <th>Trades</th>
              <th>Win rate</th>
              <th>Avg thesis accuracy</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(summary.by_strategy).map(([strategy, stats]) => (
              <tr key={strategy}>
                <td>{strategy}</td>
                <td>{stats.count}</td>
                <td>{pct(stats.win_rate)}</td>
                <td>{pct(stats.avg_thesis_accuracy)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
