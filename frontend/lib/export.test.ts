import { describe, expect, it } from "vitest";
import { toCsv } from "@/lib/export";
import type { Analysis } from "@/lib/types";

const base: Omit<Analysis, "columns" | "rows"> = {
  status: "answered",
  interpretation: null,
  sql: null,
  truncated: false,
  reason: null,
  chart: null,
};

describe("toCsv", () => {
  it("writes a header row, then one line per row, with CRLF line ends", () => {
    const csv = toCsv({ ...base, columns: ["year", "total"], rows: [[2020, 26110], [2021, 14610]] });

    expect(csv).toBe("year,total\r\n2020,26110\r\n2021,14610");
  });

  it("quotes values that would otherwise split a field or a row", () => {
    const csv = toCsv({
      ...base,
      columns: ["name", "note"],
      rows: [["Managers, Administrators", 'said "yes"'], ["two\nlines", "plain"]],
    });

    expect(csv.split("\r\n")).toEqual([
      "name,note",
      '"Managers, Administrators","said ""yes"""',
      '"two\nlines",plain',
    ]);
  });

  it("leaves a missing value empty rather than writing null", () => {
    expect(toCsv({ ...base, columns: ["a", "b"], rows: [[null, 1]] })).toBe("a,b\r\n,1");
  });
});
