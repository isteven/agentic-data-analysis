import type { Analysis, Cell } from "@/lib/types";

/** Shapes a query result into chart points. Kept apart from the drawing
 *  (components/ResultChart.tsx) so the rules can be tested without rendering. */

export type Point = Record<string, Cell>;

// x-axis key when the result has no label column (a bare number): the category is
// named after the value(s), e.g. a single bar labelled "total".
export const CATEGORY = "__category";

/** The rows to draw: a long list is sorted to the end the question is about, then cut. */
export function chartRows(analysis: Analysis): Cell[][] {
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
export function toPoints(analysis: Analysis): { points: Point[]; series: string[] } {
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

/** Whether the result has a chart to draw, so callers can skip an empty chart. */
export function hasChart(analysis: Analysis | null): boolean {
  const chart = analysis?.chart;
  if (!analysis || !chart) return false;
  return toPoints(analysis).points.length > 0;
}
