import { apiGet } from "@/lib/api-client";
import { DataSourceBadge } from "@/components/common/DataSourceBadge";

interface AgentExecution {
  outputs: {
    model?: string;
    run?: string;
    comparison_run?: string;
    hdd_delta?: number;
    cdd_delta?: number;
    estimated_rescom_delta_bcf?: number;
    estimated_power_burn_delta_bcf?: number;
    total_demand_delta_bcf?: number;
    price_direction?: string;
  };
  confidence: number | null;
  last_execution_time: string;
}

export async function WeatherPanel() {
  const executions = await apiGet<AgentExecution[]>("/agents/WEATHER/executions?limit=1").catch(() => []);
  const latest = executions[executions.length - 1];

  const isSimulated = latest?.outputs.model === "SIMULATED_FALLBACK";

  return (
    <div className="panel">
      <div className="flex items-center justify-between">
        <div className="panel-title">Weather — Model Run Delta</div>
        {latest && <DataSourceBadge classification={isSimulated ? "SIMULATED" : "PUBLIC"} />}
      </div>
      {latest ? (
        <>
          <div className="text-xs text-terminal-muted mb-1">
            {latest.outputs.model} {latest.outputs.run} vs {latest.outputs.comparison_run}
          </div>
          <table className="mono-table">
            <tbody>
              <tr>
                <td>HDD delta</td>
                <td className="text-right">{latest.outputs.hdd_delta?.toFixed(2)}</td>
              </tr>
              <tr>
                <td>CDD delta</td>
                <td className="text-right">{latest.outputs.cdd_delta?.toFixed(2)}</td>
              </tr>
              <tr>
                <td>Res/Comm demand delta</td>
                <td className="text-right">{latest.outputs.estimated_rescom_delta_bcf?.toFixed(2)} Bcf/d</td>
              </tr>
              <tr>
                <td>Power burn demand delta</td>
                <td className="text-right">{latest.outputs.estimated_power_burn_delta_bcf?.toFixed(2)} Bcf/d</td>
              </tr>
              <tr className="border-t border-terminal-border">
                <td>Total demand delta</td>
                <td
                  className={`text-right font-semibold ${
                    (latest.outputs.total_demand_delta_bcf ?? 0) >= 0 ? "text-terminal-bull" : "text-terminal-bear"
                  }`}
                >
                  {latest.outputs.total_demand_delta_bcf?.toFixed(2)} Bcf/d ({latest.outputs.price_direction})
                </td>
              </tr>
            </tbody>
          </table>
        </>
      ) : (
        <div className="text-xs text-terminal-muted">No weather agent runs recorded yet.</div>
      )}
    </div>
  );
}
