"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api-client";
import { DataSourceBadge } from "@/components/common/DataSourceBadge";
import { FreshnessTag } from "@/components/status/FreshnessTag";
import { useLiveRefetch } from "@/lib/live-events-context";

interface CurvePoint {
  symbol: string;
  curve_position: string;
  price: number;
  observation_time: string;
  classification: string;
}

export function ForwardCurveChart() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [points, setPoints] = useState<CurvePoint[] | null>(null);
  const [instrument, setInstrument] = useState<string>("M1");
  const [asOf, setAsOf] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    // The path segment is vestigial — the API always returns the single continuous
    // Henry Hub curve and reports the real (month-rolling) M1 symbol in the body.
    fetch(`${API_BASE}/market/curve/front-month`)
      .then((r) => r.json())
      .then((data) => {
        setPoints(data.points);
        setInstrument(data.instrument);
        setAsOf(data.as_of);
      })
      .catch(() => setError("Unable to load forward curve"));
  }, []);

  useEffect(load, [load]);
  // The worker refreshes prices on MARKET_REFRESH_SECONDS and publishes
  // MARKET_PRICE_UPDATED; redraw as soon as that lands rather than on a reload.
  useLiveRefetch(["MARKET_PRICE_UPDATED"], load);

  const classification = points?.[0]?.classification;

  useEffect(() => {
    if (!points || !containerRef.current) return;
    let disposed = false;
    let chart: import("lightweight-charts").IChartApi | undefined;

    import("lightweight-charts").then(({ createChart, ColorType }) => {
      if (disposed || !containerRef.current) return;
      containerRef.current.innerHTML = "";
      chart = createChart(containerRef.current, {
        width: containerRef.current.clientWidth,
        height: 260,
        layout: { background: { type: ColorType.Solid, color: "#11161f" }, textColor: "#7c8798" },
        grid: { vertLines: { color: "#1f2733" }, horzLines: { color: "#1f2733" } },
        rightPriceScale: { borderColor: "#1f2733" },
        timeScale: { borderColor: "#1f2733" },
      });
      const series = chart.addLineSeries({ color: "#3fb6a8", lineWidth: 2 });
      series.setData(
        points.map((p, i) => ({ time: (i + 1) as unknown as import("lightweight-charts").Time, value: p.price }))
      );
      chart.timeScale().fitContent();
    });

    return () => {
      disposed = true;
      chart?.remove();
    };
  }, [points]);

  return (
    <div className="panel">
      <div className="flex items-center justify-between">
        <div className="panel-title">Forward Curve — {instrument} (M1-M36)</div>
        {classification && <DataSourceBadge classification={classification} />}
      </div>
      {classification === "SIMULATED" && (
        <div className="text-[10px] text-terminal-warn">
          Real-Time NYMEX Data Not Enabled — showing a simulated curve for demonstration; no commercial CME/ICE
          license is configured for this deployment.
        </div>
      )}
      {classification && <FreshnessTag asOf={asOf} />}
      {error && <div className="text-xs text-terminal-warn">{error}</div>}
      <div ref={containerRef} className="w-full" style={{ height: 260 }} />
    </div>
  );
}
