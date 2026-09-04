import { apiGet } from "@/lib/api-client";
import { ChallengeAiButton } from "./ChallengeAiButton";

interface TradeIdea {
  trade_id: string;
  strategy: string;
  instrument: string;
  direction: string;
  entry: number;
  target: number;
  stop_or_invalidation: number;
  expected_return: number;
  probability_success: number;
  confidence: number;
  thesis: string;
  catalysts: string[];
  risks: string[];
}

export async function RecommendationsList() {
  const trades = await apiGet<TradeIdea[]>("/trade-ideas").catch(() => []);

  if (trades.length === 0) {
    return (
      <div className="panel">
        <div className="panel-title">AI Recommendations</div>
        <div className="text-xs text-terminal-muted">
          No active trade ideas. The Chief Trading Agent has not surfaced a confluence of signals right now.
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {trades.map((trade) => (
        <div key={trade.trade_id} className="panel">
          <div className="flex items-center justify-between">
            <div className="font-mono text-sm">
              <span className={trade.direction === "LONG" ? "text-terminal-bull" : "text-terminal-bear"}>
                {trade.direction}
              </span>{" "}
              {trade.instrument} · <span className="text-terminal-muted">{trade.strategy}</span>
            </div>
            <span className="text-[10px] text-terminal-muted">
              confidence {(trade.confidence * 100).toFixed(0)}% · P(success) {(trade.probability_success * 100).toFixed(0)}%
            </span>
          </div>
          <div className="mt-2 grid grid-cols-3 gap-2 text-xs font-mono">
            <div>
              <span className="text-terminal-muted">Entry </span>
              {trade.entry}
            </div>
            <div>
              <span className="text-terminal-muted">Target </span>
              {trade.target}
            </div>
            <div>
              <span className="text-terminal-muted">Invalidation </span>
              {trade.stop_or_invalidation}
            </div>
          </div>
          <p className="mt-2 text-sm text-terminal-text">{trade.thesis}</p>
          <div className="mt-2 text-xs text-terminal-muted">
            <div>Catalysts: {trade.catalysts.join("; ")}</div>
            <div>Risks: {trade.risks.join("; ")}</div>
          </div>
          <div className="mt-3">
            <ChallengeAiButton tradeId={trade.trade_id} />
          </div>
        </div>
      ))}
    </div>
  );
}
