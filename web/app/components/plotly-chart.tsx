"use client";

import { useEffect, useRef } from "react";

type PlotlyModule = {
  newPlot: (
    root: HTMLElement,
    data: unknown[],
    layout?: Record<string, unknown>,
    config?: Record<string, unknown>,
  ) => Promise<unknown>;
  purge: (root: HTMLElement) => void;
  Plots: { resize: (root: HTMLElement) => void };
};

type PlotlyChartProps = {
  data: unknown[];
  layout?: Record<string, unknown>;
  className?: string;
  ariaLabel: string;
};

export function PlotlyChart({ data, layout, className, ariaLabel }: PlotlyChartProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const node = rootRef.current;
    if (!node) return;

    let cancelled = false;
    let plotly: PlotlyModule | null = null;
    const onResize = () => {
      if (plotly && rootRef.current) plotly.Plots.resize(rootRef.current);
    };

    void import("plotly.js-basic-dist-min").then((mod) => {
      if (cancelled || !rootRef.current) return;
      plotly = mod as unknown as PlotlyModule;
      void plotly.newPlot(
        rootRef.current,
        data,
        {
          paper_bgcolor: "rgba(0,0,0,0)",
          plot_bgcolor: "rgba(0,0,0,0)",
          font: {
            family: "Geist, Segoe UI, sans-serif",
            color: "#334155",
            size: 12,
          },
          margin: { l: 48, r: 16, t: 28, b: 40 },
          ...layout,
        },
        {
          displayModeBar: false,
          responsive: true,
        },
      );
      window.addEventListener("resize", onResize);
    });

    return () => {
      cancelled = true;
      window.removeEventListener("resize", onResize);
      if (plotly && rootRef.current) plotly.purge(rootRef.current);
    };
  }, [data, layout]);

  return (
    <div
      ref={rootRef}
      className={className ?? "plotly-chart"}
      role="img"
      aria-label={ariaLabel}
    />
  );
}
