"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import { useLiveRefetch } from "@/lib/live-events-context";

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

export function RiskSummaryCard() {
  const { token } = useAuth();
  const [risk, setRisk] = useState<PortfolioRisk | null>(null);

  const load = useCallback(() => {
    // Risk Analytics requires the `risk_analytics` feature entitlement as of
    // Milestone 5 (docs/access-model.md §5) -- without a session token there is
    // nothing to fetch, so this stays a client component (a Server Component has no
    // access to the browser-held session token from apps/web/lib/auth-context.tsx).
    if (!token) {
      setRisk(null);
      return;
    }
    apiGet<PortfolioRisk>("/risk/portfolio", token)
      .then(setRisk)
      .catch(() => setRisk(null));
  }, [token]);

  useEffect(load, [load]);
  // Risk is a function of positions and prices — refetch when either moves, and
  // immediately on a breach, which is the case an operator must not miss.
  useLiveRefetch(
    ["RISK_LIMIT_BREACHED", "POSITION_UPDATED", "TRADE_APPROVED", "MARKET_PRICE_UPDATED"],
    load,
  );

  if (!token) {
    return (
      <div className="panel">
        <div className="panel-title">Risk</div>
        <div className="text-xs text-terminal-muted">Sign in to an entitled account to view risk analytics.</div>
      </div>
    );
  }

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
