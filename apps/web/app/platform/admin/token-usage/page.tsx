"use client";

import { useCallback, useEffect, useState } from "react";
import { apiGet } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface Bucket { calls: number; input_tokens: number; output_tokens: number; cost_usd: number }
interface ByModel extends Bucket { model: string }
interface Summary { today: Bucket; last7: Bucket; last30: Bucket; all: Bucket; by_model: ByModel[] }

const fmt = (n: number) => n.toLocaleString();
const usd = (n: number) => "$" + (n ?? 0).toFixed(n < 1 ? 4 : 2);

export default function TokenUsagePage() {
  const { token } = useAuth();
  const [data, setData] = useState<Summary | null>(null);
  const [forbidden, setForbidden] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      setData(await apiGet<Summary>("/admin/token-usage/summary", token));
    } catch {
      setForbidden(true);
    }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  if (forbidden) {
    return (
      <div className="panel max-w-md">
        <div className="panel-title">Token usage</div>
        <p className="text-xs text-terminal-muted">Reserved for a SUPER_ADMIN account (<code>admin.system_settings</code>).</p>
      </div>
    );
  }
  if (!data) return <p className="text-xs text-terminal-muted">Loading…</p>;

  const cards: [string, Bucket][] = [["Today", data.today], ["Last 7 days", data.last7], ["Last 30 days", data.last30], ["All time", data.all]];

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-sm font-semibold">Token usage &amp; cost</h1>
        <p className="text-xs text-terminal-muted">Claude token spend across every agent. Records once you set an Anthropic key and run an analysis.</p>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {cards.map(([label, b]) => (
          <div key={label} className="panel">
            <div className="panel-title">{label}</div>
            <div className="text-2xl font-semibold text-terminal-text">{usd(b.cost_usd)}</div>
            <div className="mt-1 text-[11px] text-terminal-muted">
              {fmt(b.calls)} calls · {fmt(b.input_tokens)} in / {fmt(b.output_tokens)} out
            </div>
          </div>
        ))}
      </div>

      <div className="panel">
        <div className="panel-title">By model</div>
        {data.by_model.length === 0 ? (
          <p className="text-xs text-terminal-muted">
            No usage yet. Add an <code>ANTHROPIC_API_KEY</code> in Configuration, then run an analysis — real Claude calls will show up here with their cost.
          </p>
        ) : (
          <table className="mono-table">
            <thead><tr><th>Model</th><th>Calls</th><th>Input</th><th>Output</th><th>Cost</th></tr></thead>
            <tbody>
              {data.by_model.map((m) => (
                <tr key={m.model}>
                  <td className="text-terminal-text">{m.model}</td>
                  <td>{fmt(m.calls)}</td>
                  <td>{fmt(m.input_tokens)}</td>
                  <td>{fmt(m.output_tokens)}</td>
                  <td className="text-terminal-text">{usd(m.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
