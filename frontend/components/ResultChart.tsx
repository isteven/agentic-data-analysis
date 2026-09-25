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
import type { Analysis, Cell } from "@/lib/types";

// Distinct in both light and dark themes; series beyond this wrap around.
const SERIES_COLORS = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#65a30d"];

type Point = Record<string, Cell>;

/**
 * Rows as chart points. With a group column, rows are pivoted so each group value
 * becomes its own series: [{year, sex: "Male", v}, {year, sex: "Female", v}]
 * -> [{year, Male: v, Female: v}].
 */
function toPoints(analysis: Analysis): { points: Point[]; series: string[] } {
  const { columns, rows, chart } = analysis;
  const idx = (name: string) => columns.indexOf(name);
  if (!chart?.x) return { points: [], series: [] };

  if (!chart.group) {
    const points = rows.map((row) => Object.fromEntries(columns.map((c, i) => [c, row[i]])));
    return { points, series: chart.y };
  }

  const [xi, gi, yi] = [idx(chart.x), idx(chart.group), idx(chart.y[0])];
  const byX = new Map<string, Point>();
  const series: string[] = [];
  for (const row of rows) {
    const key = String(row[xi]);
    const group = String(row[gi]);
    if (!series.includes(group)) series.push(group);
    const point = byX.get(key) ?? { [chart.x]: row[xi] };
    point[group] = row[yi];
    byX.set(key, point);
  }
  return { points: [...byX.values()], series };
}

const formatNumber = (value: unknown) =>
  typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(value);

/** Whether the result has a chart to draw, so callers can hide an empty chart tab. */
export function hasChart(analysis: Analysis | null): boolean {
  const chart = analysis?.chart;
  if (!analysis || !chart || chart.type === "none" || !chart.x) return false;
  return toPoints(analysis).points.length > 0;
}

/** `ref` is forwarded to the chart's container div, so a caller (the export button)
 * can find the rendered <svg> via ref.current.querySelector("svg"). */
export const ResultChart = forwardRef<HTMLDivElement, { analysis: Analysis }>(function ResultChart(
  { analysis },
  ref,
) {
  const chart = analysis.chart;
  if (!chart || !hasChart(analysis) || !chart.x) return null;

  const { points, series } = toPoints(analysis);

  const common = (
    <>
      <CartesianGrid strokeDasharray="3 3" stroke="#a1a1aa" strokeOpacity={0.3} />
      <XAxis dataKey={chart.x} tick={{ fontSize: 12 }} />
      <YAxis tick={{ fontSize: 12 }} tickFormatter={formatNumber} width={70} />
      <Tooltip formatter={formatNumber} />
      {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
    </>
  );

  return (
    <figure>
      <div ref={ref} className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {chart.type === "bar" ? (
            <BarChart data={points}>
              {common}
              {series.map((s, i) => (
                <Bar key={s} dataKey={s} fill={SERIES_COLORS[i % SERIES_COLORS.length]} />
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
                  stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
                  strokeWidth={2}
                  dot={{ r: 3 }}
                />
              ))}
            </LineChart>
          )}
        </ResponsiveContainer>
      </div>
      {analysis.interpretation && (
        <figcaption className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
          {analysis.interpretation}
        </figcaption>
      )}
    </figure>
  );
});
