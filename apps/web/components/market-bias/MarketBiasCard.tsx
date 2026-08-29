import { apiGet } from "@/lib/api-client";

interface MarketBiasDriver {
  name: string;
  points: number;
  rationale: string;
}

interface MarketBiasResponse {
  label: string;
  score: number | null;
  drivers: MarketBiasDriver[];
  computed_at: string;
}

const LABEL_COLOR: Record<string, string> = {
  STRONGLY_BULLISH: "text-terminal-bull",
  BULLISH: "text-terminal-bull",
  NEUTRAL: "text-terminal-muted",
  BEARISH: "text-terminal-bear",
  STRONGLY_BEARISH: "text-terminal-bear",
};

function labelText(label: string): string {
  return label.replace(/_/g, " ");
}

export async function MarketBiasCard() {
  const bias = await apiGet<MarketBiasResponse>("/alpha/market-bias").catch(() => null);

  return (
    <div className="panel">
      <div className="panel-title">Market Bias</div>
      <p className="text-[10px] text-terminal-muted mb-2">
        A deterministic, weighted score -- never an LLM's judgment call. Every driver below is a
        real, reproducible number.
      </p>
      {!bias || bias.label === "INSUFFICIENT_DATA" ? (
        <div className="text-xs text-terminal-muted">Insufficient data to compute a bias right now.</div>
      ) : (
        <>
          <div className={`font-mono text-2xl ${LABEL_COLOR[bias.label] ?? ""}`}>
            {labelText(bias.label)}
            {bias.score != null && (
              <span className="ml-2 text-sm text-terminal-muted">{bias.score.toFixed(0)}/100</span>
            )}
          </div>
          <div className="mt-2 space-y-0.5">
            {bias.drivers.map((d) => (
              <div key={d.name} className="flex items-center justify-between text-[11px]" title={d.rationale}>
                <span className="text-terminal-muted">{d.name}</span>
                <span className={d.points >= 0 ? "text-terminal-bull" : "text-terminal-bear"}>
                  {d.points > 0 ? "+" : ""}
                  {d.points.toFixed(1)}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
