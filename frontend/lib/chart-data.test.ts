import { describe, expect, it } from "vitest";
import { CATEGORY, hasChart, toPoints } from "@/lib/chart-data";
import type { Analysis, ChartSpec } from "@/lib/types";

function analysis(columns: string[], rows: Analysis["rows"], chart: Partial<ChartSpec> | null): Analysis {
  return {
    status: "answered",
    interpretation: null,
    sql: "SELECT ...",
    columns,
    rows,
    truncated: false,
    reason: null,
    chart: chart && { type: "bar", x: null, y: [], group: null, limit: null, sort: null, source: "planner", ...chart },
  };
}

describe("toPoints", () => {
  it("draws a long list from the end the question is about, cut to the limit", () => {
    const rows = [["A", 5], ["B", 1], ["C", 3], ["D", 2]];
    const shortest = analysis(["station", "minutes"], rows, { x: "station", y: ["minutes"], limit: 2, sort: "asc" });
    const longest = analysis(["station", "minutes"], rows, { x: "station", y: ["minutes"], limit: 2, sort: "desc" });

    expect(toPoints(shortest).points.map((p) => p.station)).toEqual(["B", "D"]);
    expect(toPoints(longest).points.map((p) => p.station)).toEqual(["A", "C"]);
  });

  it("keeps the query's order when there is no sort", () => {
    const res = analysis(["station", "minutes"], [["A", 5], ["B", 1], ["C", 3]], { x: "station", y: ["minutes"], limit: 2 });

    expect(toPoints(res).points.map((p) => p.station)).toEqual(["A", "B"]);
  });

  it("turns a group column into one series per group", () => {
    const res = analysis(
      ["year", "sex", "value"],
      [[2023, "Male", 1], [2023, "Female", 2], [2024, "Male", 3], [2024, "Female", 4]],
      { type: "line", x: "year", y: ["value"], group: "sex" },
    );

    const { points, series } = toPoints(res);

    expect(series).toEqual(["Male", "Female"]);
    expect(points).toEqual([
      { year: 2023, Male: 1, Female: 2 },
      { year: 2024, Male: 3, Female: 4 },
    ]);
  });

  it("draws a bare number as one bar named after the value", () => {
    const res = analysis(["total"], [[14380]], { x: null, y: ["total"] });

    expect(toPoints(res).points).toEqual([{ [CATEGORY]: "total", total: 14380 }]);
  });
});

describe("hasChart", () => {
  it("is false when there is nothing to draw", () => {
    expect(hasChart(null)).toBe(false);
    expect(hasChart(analysis(["university"], [["NUS"]], { type: "none" }))).toBe(false);
    expect(hasChart(analysis(["year", "value"], [], { type: "line", x: "year", y: ["value"] }))).toBe(false);
  });

  it("is true for a chart spec with rows", () => {
    expect(hasChart(analysis(["year", "value"], [[2023, 1]], { x: "year", y: ["value"] }))).toBe(true);
  });
});
