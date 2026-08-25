import { apiGet } from "@/lib/api-client";
import { DataSourceBadge } from "@/components/common/DataSourceBadge";
import { AuthWidget } from "@/components/auth/AuthWidget";

interface MarketSummary {
  hh_m1: number;
  hh_m1_symbol: string;
  hh_m2: number;
  twelve_month_strip_avg: number | null;
  nav: number;
  daily_pnl: number;
  unrealized_pnl: number;
  var_95: number;
  ai_market_bias: string;
  classification: string;
  as_of: string;
}

function stat(label: string, value: string, accent?: string) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-terminal-muted">{label}</span>
      <span className={`font-mono text-sm ${accent ?? "text-terminal-text"}`}>{value}</span>
    </div>
  );
}

export async function HeaderBar() {
  let summary: MarketSummary | null = null;
  try {
    summary = await apiGet<MarketSummary>("/market/summary");
  } catch {
    summary = null;
  }

  return (
    <header className="border-b border-terminal-border bg-terminal-panel px-4 py-2">
      <div className="flex items-center justify-between">
        <div className="flex items-baseline gap-2">
          <span className="font-semibold text-terminal-text tracking-tight">AlphaGasIQ</span>
          <span className="text-[10px] text-terminal-muted">Powered by Elavo AI</span>
          {summary && <DataSourceBadge classification={summary.classification} />}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[10px] text-terminal-muted">
            Decision-support &amp; paper-trading — no live orders are ever routed
          </span>
          <AuthWidget />
        </div>
      </div>
      {summary ? (
        <div className="mt-2 flex flex-wrap gap-6">
          {stat(`HH ${summary.hh_m1_symbol} (M1)`, summary.hh_m1.toFixed(3))}
          {stat("M2", summary.hh_m2.toFixed(3))}
          {stat("12-mo strip avg", summary.twelve_month_strip_avg?.toFixed(3) ?? "—")}
          {stat("Portfolio NAV", `$${summary.nav.toLocaleString()}`)}
          {stat(
            "Daily P&L",
            `$${summary.daily_pnl.toFixed(2)}`,
            summary.daily_pnl >= 0 ? "text-terminal-bull" : "text-terminal-bear"
          )}
          {stat("Unrealized P&L", `$${summary.unrealized_pnl.toFixed(2)}`)}
          {stat("VaR (95%)", `$${summary.var_95.toFixed(2)}`)}
          {stat(
            "AI Market Bias",
            summary.ai_market_bias,
            summary.ai_market_bias === "BULLISH"
              ? "text-terminal-bull"
              : summary.ai_market_bias === "BEARISH"
              ? "text-terminal-bear"
              : "text-terminal-text"
          )}
          {stat("System Status", "ONLINE", "text-terminal-bull")}
        </div>
      ) : (
        <div className="mt-2 text-xs text-terminal-warn">
          Unable to reach the AlphaGasIQ API — is `apps/api` running?
        </div>
      )}
    </header>
  );
}
