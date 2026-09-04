import { apiGet } from "@/lib/api-client";

interface PriceForecast {
  instrument: string;
  horizon: string;
  price_forecast: number;
  return_forecast: number;
  up_probability: number;
  confidence: number;
}

interface RegimeResult {
  regime: string;
  confidence: number;
  drivers: string[];
}

interface RelativeValue {
  hh_ttf_netback: { direction: string; mispricing: number; rationale: string };
  calendar_spread: { direction: string; mispricing: number; rationale: string };
}

interface BacktestModelResult {
  model_type: string;
  n_folds: number;
  mae: number;
  directional_accuracy: number;
  hit_rate: number;
  sharpe_ratio: number | null;
}

interface BacktestResponse {
  results_by_model: Record<string, BacktestModelResult>;
}

const REGIME_COLOR: Record<string, string> = {
  NORMAL: "text-terminal-text",
  LOW_VOLATILITY: "text-terminal-accent",
  HIGH_VOLATILITY: "text-terminal-warn",
  WEATHER_SHOCK: "text-terminal-warn",
  SUPPLY_SHOCK: "text-terminal-bear",
  DEMAND_SHOCK: "text-terminal-bull",
  STORAGE_STRESS: "text-terminal-warn",
  LNG_SHOCK: "text-terminal-warn",
  PIPELINE_CONSTRAINT: "text-terminal-warn",
  GEOPOLITICAL_SHOCK: "text-terminal-bear",
};

export async function QuantPanel() {
  const [forecast, regime, rv, backtest] = await Promise.all([
    apiGet<PriceForecast>("/quant/forecast").catch(() => null),
    apiGet<RegimeResult>("/quant/regime").catch(() => null),
    apiGet<RelativeValue>("/quant/relative-value").catch(() => null),
    apiGet<BacktestResponse>("/quant/backtest").catch(() => null),
  ]);

  return (
    <div className="panel">
      <div className="panel-title">Quantitative Team</div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
        <div>
          <div className="text-[10px] text-terminal-muted uppercase">Forecast ({forecast?.horizon ?? "—"})</div>
          {forecast ? (
            <>
              <div className="font-mono text-sm">
                {forecast.instrument} → {forecast.price_forecast.toFixed(3)}{" "}
                <span className={forecast.return_forecast >= 0 ? "text-terminal-bull" : "text-terminal-bear"}>
                  ({forecast.return_forecast >= 0 ? "+" : ""}
                  {forecast.return_forecast.toFixed(3)})
                </span>
              </div>
              <div className="text-terminal-muted">
                {(forecast.up_probability * 100).toFixed(0)}% up-probability · confidence{" "}
                {(forecast.confidence * 100).toFixed(0)}%
              </div>
            </>
          ) : (
            <div className="text-terminal-muted">Not yet generated.</div>
          )}
        </div>

        <div>
          <div className="text-[10px] text-terminal-muted uppercase">Regime</div>
          {regime ? (
            <>
              <div className={`font-mono text-sm ${REGIME_COLOR[regime.regime] ?? "text-terminal-text"}`}>
                {regime.regime}
              </div>
              <div className="text-terminal-muted">{regime.drivers[0]}</div>
            </>
          ) : (
            <div className="text-terminal-muted">Not yet classified.</div>
          )}
        </div>

        <div>
          <div className="text-[10px] text-terminal-muted uppercase">Relative Value</div>
          {rv ? (
            <>
              <div>
                HH-TTF netback: <span className="font-mono">{rv.hh_ttf_netback.direction}</span>
              </div>
              <div>
                Calendar spread: <span className="font-mono">{rv.calendar_spread.direction}</span>
              </div>
            </>
          ) : (
            <div className="text-terminal-muted">Not yet computed.</div>
          )}
        </div>

        <div>
          <div className="text-[10px] text-terminal-muted uppercase">Walk-Forward Backtest</div>
          {backtest ? (
            <table className="mono-table">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Folds</th>
                  <th>Dir. acc.</th>
                  <th>MAE</th>
                </tr>
              </thead>
              <tbody>
                {Object.values(backtest.results_by_model).map((r) => (
                  <tr key={r.model_type}>
                    <td>{r.model_type}</td>
                    <td>{r.n_folds}</td>
                    <td>{(r.directional_accuracy * 100).toFixed(0)}%</td>
                    <td>{r.mae.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="text-terminal-muted">Not yet run.</div>
          )}
        </div>
      </div>
    </div>
  );
}
