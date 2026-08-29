import { apiGet } from "@/lib/api-client";
import { DataSourceBadge } from "@/components/common/DataSourceBadge";

interface BalanceDay {
  flow_date: string;
  supply_total_bcf: number;
  demand_total_bcf: number;
  balance_bcf: number;
  classification: string;
}

interface StorageForecast {
  forecast_bcf: number;
  market_consensus_bcf: number | null;
}

interface LngResponse {
  terminals: { feedgas_bcf_d: number }[];
}

interface PowerBurnResponse {
  total_power_burn_bcf_d: number;
}

function Card({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="panel min-w-[150px]">
      <div className="panel-title">{label}</div>
      <div className="font-mono text-lg text-terminal-text">{value}</div>
      {sub && <div className="text-[10px] text-terminal-muted mt-1">{sub}</div>}
    </div>
  );
}

export async function MarketIntelGrid() {
  const [balances, storage, lng, powerBurn] = await Promise.all([
    apiGet<BalanceDay[]>("/fundamentals/balance/daily?days=1").catch(() => []),
    apiGet<StorageForecast>("/fundamentals/storage/forecast").catch(() => null),
    apiGet<LngResponse>("/fundamentals/lng/terminals").catch(() => null),
    apiGet<PowerBurnResponse>("/fundamentals/power-burn").catch(() => null),
  ]);

  const latest = balances[0];
  const feedgasTotal = lng?.terminals.reduce((sum, t) => sum + t.feedgas_bcf_d, 0) ?? null;

  return (
    <div className="space-y-1">
      {latest && (
        <div className="flex items-center gap-1.5">
          <DataSourceBadge classification={latest.classification} />
          <span className="text-[10px] text-terminal-muted">
            Balance/LNG/power-burn are Phase 1 seed data -- no free daily-granularity fundamentals source exists yet.
          </span>
        </div>
      )}
      <div className="flex flex-wrap gap-3">
        <Card label="Lower 48 Production" value={latest ? `${latest.supply_total_bcf.toFixed(1)} Bcf/d` : "—"} />
        <Card label="LNG Feedgas" value={feedgasTotal !== null ? `${feedgasTotal.toFixed(1)} Bcf/d` : "—"} />
        <Card label="Power Burn" value={powerBurn ? `${powerBurn.total_power_burn_bcf_d.toFixed(1)} Bcf/d` : "—"} />
        <Card
          label="Storage Forecast"
          value={storage ? `${storage.forecast_bcf > 0 ? "+" : ""}${storage.forecast_bcf} Bcf` : "—"}
          sub={storage?.market_consensus_bcf != null ? `consensus ${storage.market_consensus_bcf} Bcf` : undefined}
        />
        <Card label="Total Demand" value={latest ? `${latest.demand_total_bcf.toFixed(1)} Bcf/d` : "—"} />
        <Card
          label="Net Balance"
          value={latest ? `${latest.balance_bcf > 0 ? "+" : ""}${latest.balance_bcf.toFixed(1)} Bcf/d` : "—"}
        />
      </div>
    </div>
  );
}
