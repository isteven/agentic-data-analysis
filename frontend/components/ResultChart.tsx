"use client";

import { forwardRef } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { CATEGORY, hasChart, toPoints } from "@/lib/chart-data";
import type { Analysis } from "@/lib/types";
import styles from "./ResultChart.module.css";

// Theme tokens (app/globals.css), so charts use the app theme's colours; series
// beyond the eighth wrap around.
const SERIES_COUNT = 8;
const seriesColor = (i: number) => `var(--chart-series-${(i % SERIES_COUNT) + 1})`;
const TICK = { fontSize: 12, fill: "var(--chart-tick)" };
const TOOLTIP_STYLE = {
  background: "var(--chart-tooltip-bg)",
  borderColor: "var(--border)",
  color: "var(--chart-tooltip-text)",
};

const LONG_LABEL = 12; // characters; longer category labels switch bars to horizontal
const LABEL_WIDTH = 220;
const ROW_HEIGHT = 28;
const MIN_HEIGHT = 288;

const formatNumber = (value: unknown) =>
  typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(value);

/** `ref` is forwarded to the chart's container div, so a caller (the export button)
 * can find the rendered <svg> via ref.current.querySelector("svg"). */
export const ResultChart = forwardRef<HTMLDivElement, { analysis: Analysis }>(function ResultChart(
  { analysis },
  ref,
) {
  const chart = analysis.chart;
  if (!chart || !hasChart(analysis)) return null;

  const { points, series } = toPoints(analysis);
  const cut = chart.limit && analysis.rows.length > chart.limit ? chart.limit : null;
  const xKey = chart.x ?? CATEGORY;
  // Long category names don't fit under upright bars (most get hidden), so those
  // bars lie flat with the names down the left.
  const horizontal =
    chart.type === "bar" && points.some((p) => typeof p[xKey] === "string" && String(p[xKey]).length > LONG_LABEL);

  const common = (
    <>
      <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
      {horizontal ? (
        <>
          <XAxis type="number" tick={TICK} tickFormatter={formatNumber} />
          <YAxis type="category" dataKey={xKey} tick={{ ...TICK, fontSize: 11 }} width={LABEL_WIDTH} interval={0} />
        </>
      ) : (
        <>
          <XAxis dataKey={xKey} tick={TICK} />
          <YAxis tick={TICK} tickFormatter={formatNumber} width={70} />
        </>
      )}
      <Tooltip formatter={formatNumber} contentStyle={TOOLTIP_STYLE} labelStyle={{ color: "var(--chart-tooltip-text)" }} />
      {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
    </>
  );

  return (
    <figure>
      <div
        ref={ref}
        className={styles.chart}
        style={horizontal ? { height: Math.max(MIN_HEIGHT, points.length * ROW_HEIGHT + 40) } : undefined}
      >
        <ResponsiveContainer width="100%" height="100%">
          {chart.type === "bar" ? (
            <BarChart data={points} layout={horizontal ? "vertical" : "horizontal"}>
              {common}
              {series.map((s, i) => (
                <Bar key={s} dataKey={s} fill={seriesColor(i)} />
              ))}
            </BarChart>
          ) : (
            <LineChart data={points}>
              {common}
              {series.map((s, i) => (
                <Line
                  key={s}
                  type="monotone"
                  dataKey={s}
                  stroke={seriesColor(i)}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                />
              ))}
            </LineChart>
          )}
        </ResponsiveContainer>
      </div>
      {cut && (
        <p className={styles.note}>
          Showing the {chart.sort === "asc" ? `${cut} lowest` : chart.sort === "desc" ? `${cut} highest` : `first ${cut}`}{" "}
          of {analysis.rows.length}
          {analysis.truncated ? "+" : ""} · full list in the Data tab
        </p>
      )}
      {analysis.interpretation && (
        <figcaption className={styles.caption}>
          {analysis.interpretation}
        </figcaption>
      )}
    </figure>
  );
});
