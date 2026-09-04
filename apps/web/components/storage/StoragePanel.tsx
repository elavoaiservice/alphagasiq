import { apiGet } from "@/lib/api-client";
import { DataSourceBadge } from "@/components/common/DataSourceBadge";

interface StorageCurrent {
  current_inventory_bcf: number;
  year_ago_inventory_bcf: number;
  five_year_average_bcf: number;
  five_year_low_bcf: number;
  five_year_high_bcf: number;
  classification: string;
}

interface StorageForecast {
  week_ending: string;
  forecast_bcf: number;
  market_consensus_bcf: number | null;
  forecast_range_low: number;
  forecast_range_high: number;
  confidence: number;
}

export async function StoragePanel() {
  const [current, forecast] = await Promise.all([
    apiGet<StorageCurrent>("/fundamentals/storage/current").catch(() => null),
    apiGet<StorageForecast>("/fundamentals/storage/forecast").catch(() => null),
  ]);

  return (
    <div className="panel">
      <div className="flex items-center justify-between">
        <div className="panel-title">Storage</div>
        {current && <DataSourceBadge classification={current.classification} />}
      </div>
      {current && (
        <table className="mono-table">
          <tbody>
            <tr>
              <td>Current inventory</td>
              <td className="text-right">{current.current_inventory_bcf.toLocaleString()} Bcf</td>
            </tr>
            <tr>
              <td>Year ago</td>
              <td className="text-right">{current.year_ago_inventory_bcf.toLocaleString()} Bcf</td>
            </tr>
            <tr>
              <td>5-yr average</td>
              <td className="text-right">{current.five_year_average_bcf.toLocaleString()} Bcf</td>
            </tr>
            <tr>
              <td>5-yr range</td>
              <td className="text-right">
                {current.five_year_low_bcf.toLocaleString()} - {current.five_year_high_bcf.toLocaleString()} Bcf
              </td>
            </tr>
          </tbody>
        </table>
      )}
      {forecast && (
        <div className="mt-3 border-t border-terminal-border pt-2">
          <div className="text-xs text-terminal-muted">Next EIA print (week ending {forecast.week_ending})</div>
          <div
            className={`font-mono text-xl ${forecast.forecast_bcf >= 0 ? "text-terminal-bull" : "text-terminal-bear"}`}
          >
            {forecast.forecast_bcf > 0 ? "+" : ""}
            {forecast.forecast_bcf} Bcf
          </div>
          <div className="text-[10px] text-terminal-muted">
            range {forecast.forecast_range_low} to {forecast.forecast_range_high} Bcf · consensus{" "}
            {forecast.market_consensus_bcf ?? "n/a"} Bcf · confidence {(forecast.confidence * 100).toFixed(0)}%
          </div>
        </div>
      )}
    </div>
  );
}
