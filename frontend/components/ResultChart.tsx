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
import styles from "./ResultChart.module.css";

// Distinct in both light and dark themes; series beyond this wrap around.
const SERIES_COLORS = ["#5e81ac", "#bf616a", "#a3be8c", "#ebcb8b", "#b48ead", "#88c0d0", "#ac4c78", "#cacdc7"];

type Point = Record<string, Cell>;

// x-axis key when the result has no label column (a bare number): the category is
// named after the value(s), e.g. a single bar labelled "total".
const CATEGORY = "__category";

const LONG_LABEL = 12; // characters; longer category labels switch bars to horizontal
const LABEL_WIDTH = 220;
const ROW_HEIGHT = 28;
const MIN_HEIGHT = 288;

/** The rows to draw: a long list is sorted to the end the question is about, then cut. */
function chartRows(analysis: Analysis): Cell[][] {
  const { chart, columns, rows } = analysis;
  if (!chart?.limit) return rows;
  const yi = columns.indexOf(chart.y[0]);
  const sorted = chart.sort
    ? [...rows].sort((a, b) => (Number(a[yi]) - Number(b[yi])) * (chart.sort === "asc" ? 1 : -1))
    : rows;
  return sorted.slice(0, chart.limit);
}

/**
 * Rows as chart points. With a group column, rows are pivoted so each group value
 * becomes its own series: [{year, sex: "Male", v}, {year, sex: "Female", v}]
 * -> [{year, Male: v, Female: v}].
 */
function toPoints(analysis: Analysis): { points: Point[]; series: string[] } {
  const { columns, chart } = analysis;
  const idx = (name: string) => columns.indexOf(name);
  if (!chart || chart.type === "none" || chart.y.length === 0) return { points: [], series: [] };
  const rows = chartRows(analysis);

  if (!chart.x) {
    const points = rows.map((row, i) => ({
      [CATEGORY]: rows.length > 1 ? String(i + 1) : chart.y.join(", "),
      ...Object.fromEntries(chart.y.map((c) => [c, row[idx(c)]])),
    }));
    return { points, series: chart.y };
  }

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

/** Whether the result has a chart to draw, so callers can skip an empty chart. */
export function hasChart(analysis: Analysis | null): boolean {
  const chart = analysis?.chart;
  if (!analysis || !chart) return false;
  return toPoints(analysis).points.length > 0;
}

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
      <CartesianGrid strokeDasharray="3 3" stroke="#ffffff" strokeOpacity={0.3} />
      {horizontal ? (
        <>
          <XAxis type="number" tick={{ fontSize: 12 }} tickFormatter={formatNumber} />
          <YAxis type="category" dataKey={xKey} tick={{ fontSize: 11 }} width={LABEL_WIDTH} interval={0} />
        </>
      ) : (
        <>
          <XAxis dataKey={xKey} tick={{ fontSize: 12 }} />
          <YAxis tick={{ fontSize: 12  }} tickFormatter={formatNumber} width={70} />
        </>
      )}
      <Tooltip formatter={formatNumber} />
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
