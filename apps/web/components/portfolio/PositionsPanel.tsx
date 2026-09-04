"use client";

import { useEffect, useState } from "react";
import { API_BASE, apiPost } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";

interface Position {
  instrument: string;
  quantity: number;
  avg_price: number;
  mark_price: number;
  unrealized_pnl: number;
  realized_pnl: number;
}

interface TradeIdea {
  trade_id: string;
  instrument: string;
}

export function PositionsPanel() {
  const { token, user } = useAuth();
  const [positions, setPositions] = useState<Position[]>([]);
  const [trades, setTrades] = useState<TradeIdea[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function refresh(currentToken: string | null) {
    // Portfolio Analytics requires the `portfolio_analytics` feature entitlement as
    // of Milestone 5 (docs/access-model.md §5) -- without a token there is nothing
    // this panel can show.
    if (!currentToken) {
      setPositions([]);
      setTrades([]);
      return;
    }
    const [posRes, tradesRes] = await Promise.all([
      fetch(`${API_BASE}/portfolio/positions`, { headers: { Authorization: `Bearer ${currentToken}` } }),
      fetch(`${API_BASE}/trade-ideas`),
    ]);
    setPositions(posRes.ok ? await posRes.json() : []);
    setTrades(await tradesRes.json());
  }

  useEffect(() => {
    refresh(token);
  }, [token]);

  async function closePosition(instrument: string) {
    const trade = trades.find((t) => t.instrument === instrument);
    if (!trade) {
      setMessage("No trade idea on record for this instrument.");
      return;
    }
    if (!token) {
      setMessage("Sign in as a Trader/Risk Manager/Admin to close a position.");
      return;
    }
    setBusy(instrument);
    setMessage(null);
    try {
      const res = await apiPost<{ post_trade_analysis: { quadrant: string } }>(
        `/trade-ideas/${trade.trade_id}/close`,
        { exit_reason: "manual_close" },
        token
      );
      setMessage(`Closed. Outcome: ${res.post_trade_analysis.quadrant}`);
      await refresh(token);
    } catch {
      setMessage("Close failed.");
    } finally {
      setBusy(null);
    }
  }

  const open = positions.filter((p) => p.quantity !== 0);

  return (
    <div className="panel">
      <div className="panel-title">Paper Positions</div>
      {open.length === 0 ? (
        <div className="text-xs text-terminal-muted">No open paper positions.</div>
      ) : (
        <table className="mono-table">
          <thead>
            <tr>
              <th>Instrument</th>
              <th>Qty</th>
              <th>Avg</th>
              <th>Mark</th>
              <th>Unrealized</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {open.map((p) => (
              <tr key={p.instrument}>
                <td>{p.instrument}</td>
                <td>{p.quantity}</td>
                <td>{p.avg_price.toFixed(3)}</td>
                <td>{p.mark_price.toFixed(3)}</td>
                <td className={p.unrealized_pnl >= 0 ? "text-terminal-bull" : "text-terminal-bear"}>
                  {p.unrealized_pnl.toFixed(2)}
                </td>
                <td>
                  <button
                    disabled={busy === p.instrument}
                    onClick={() => closePosition(p.instrument)}
                    className="text-[10px] px-1.5 py-0.5 border border-terminal-warn text-terminal-warn rounded hover:bg-terminal-warn/10 disabled:opacity-50"
                  >
                    Close
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {!user && <div className="mt-2 text-[10px] text-terminal-muted">Sign in to close a position.</div>}
      {message && <div className="mt-2 text-[10px] text-terminal-warn">{message}</div>}
    </div>
  );
}
