import { apiGet } from "@/lib/api-client";

interface PortfolioRisk {
  gross_exposure: number;
  net_exposure: number;
  delta: number;
  var_95: number;
  expected_shortfall_95: number;
  max_drawdown: number;
  concentration_hhi: number;
  trading_halted: boolean;
}

export async function RiskSummaryCard() {
  const risk = await apiGet<PortfolioRisk>("/risk/portfolio").catch(() => null);
  if (!risk) {
    return (
      <div className="panel">
        <div className="panel-title">Risk</div>
        <div className="text-xs text-terminal-warn">Risk engine unreachable</div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="flex items-center justify-between">
        <div className="panel-title">Independent Risk</div>
        {risk.trading_halted && (
          <span className="text-[10px] px-1.5 py-0.5 rounded border border-terminal-bear text-terminal-bear">
            TRADING HALTED
          </span>
        )}
      </div>
      <table className="mono-table">
        <tbody>
          <tr>
            <td>Gross exposure</td>
            <td className="text-right">${risk.gross_exposure.toLocaleString()}</td>
          </tr>
          <tr>
            <td>Net exposure</td>
            <td className="text-right">${risk.net_exposure.toLocaleString()}</td>
          </tr>
          <tr>
            <td>Delta</td>
            <td className="text-right">{risk.delta}</td>
          </tr>
          <tr>
            <td>VaR (95%)</td>
            <td className="text-right">${risk.var_95.toLocaleString()}</td>
          </tr>
          <tr>
            <td>Expected Shortfall (95%)</td>
            <td className="text-right">${risk.expected_shortfall_95.toLocaleString()}</td>
          </tr>
          <tr>
            <td>Max drawdown</td>
            <td className="text-right">{(risk.max_drawdown * 100).toFixed(1)}%</td>
          </tr>
          <tr>
            <td>Concentration (HHI)</td>
            <td className="text-right">{risk.concentration_hhi}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
