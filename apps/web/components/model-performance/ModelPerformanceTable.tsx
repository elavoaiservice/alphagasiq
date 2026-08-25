import { apiGet } from "@/lib/api-client";

interface StrategyStats {
  count: number;
  wins: number;
  avg_thesis_accuracy: number;
  win_rate: number;
}

interface PerformanceSummary {
  closed_trade_count: number;
  win_rate: number | null;
  avg_thesis_accuracy: number | null;
  avg_timing_accuracy: number | null;
  avg_risk_accuracy: number | null;
  by_quadrant: Record<string, number>;
  by_strategy: Record<string, StrategyStats>;
  classification: string;
}

const QUADRANT_LABELS: Record<string, string> = {
  GOOD_DECISION_GOOD_OUTCOME: "Good decision / good outcome",
  GOOD_DECISION_BAD_OUTCOME: "Good decision / bad outcome",
  BAD_DECISION_GOOD_OUTCOME: "Bad decision / good outcome",
  BAD_DECISION_BAD_OUTCOME: "Bad decision / bad outcome",
};

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
      <div className="panel">
        <div className="panel-title">Model Performance</div>
        <div className="text-xs text-terminal-muted">
          No trades have closed yet. Approve a recommendation and close the resulting position (see the
          dashboard&apos;s Approval Queue and Paper Positions panels) to start building a performance record.
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
            {((summary.win_rate ?? 0) * 100).toFixed(0)}%
          </div>
          <div>
            <div className="text-[10px] text-terminal-muted">Avg thesis accuracy</div>
            {((summary.avg_thesis_accuracy ?? 0) * 100).toFixed(0)}%
          </div>
          <div>
            <div className="text-[10px] text-terminal-muted">Avg timing accuracy</div>
            {((summary.avg_timing_accuracy ?? 0) * 100).toFixed(0)}%
          </div>
          <div>
            <div className="text-[10px] text-terminal-muted">Avg risk accuracy</div>
            {((summary.avg_risk_accuracy ?? 0) * 100).toFixed(0)}%
          </div>
        </div>
      </div>

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
                <td>{(stats.win_rate * 100).toFixed(0)}%</td>
                <td>{(stats.avg_thesis_accuracy * 100).toFixed(0)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
