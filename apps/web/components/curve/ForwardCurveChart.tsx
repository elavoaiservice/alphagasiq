"use client";

import { useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api-client";

interface CurvePoint {
  symbol: string;
  curve_position: string;
  price: number;
  observation_time: string;
}

export function ForwardCurveChart({ instrument }: { instrument: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [points, setPoints] = useState<CurvePoint[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/market/curve/${instrument}`)
      .then((r) => r.json())
      .then((data) => {
        if (!cancelled) setPoints(data.points);
      })
      .catch(() => !cancelled && setError("Unable to load forward curve"));
    return () => {
      cancelled = true;
    };
  }, [instrument]);

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
      <div className="panel-title">Forward Curve — {instrument} (M1-M36)</div>
      {error && <div className="text-xs text-terminal-warn">{error}</div>}
      <div ref={containerRef} className="w-full" style={{ height: 260 }} />
    </div>
  );
}
