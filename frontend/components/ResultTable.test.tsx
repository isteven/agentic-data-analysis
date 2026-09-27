import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ResultTable } from "@/components/ResultTable";
import type { Analysis } from "@/lib/types";

function analysis(overrides: Partial<Analysis> = {}): Analysis {
  return {
    status: "answered",
    interpretation: null,
    sql: "SELECT year, retrench_total FROM data.retrenchment",
    columns: ["year", "retrench_total"],
    rows: [[2020, 26110]],
    truncated: false,
    reason: null,
    time_columns: ["year"],
    chart: null,
    ...overrides,
  };
}

const cells = () => screen.getAllByRole("cell").map((c) => c.textContent);

describe("ResultTable", () => {
  it("shows time values as labels and quantities with separators", () => {
    render(<ResultTable analysis={analysis()} />);

    expect(cells()).toEqual(["2020", (26110).toLocaleString()]);
  });

  it("treats whichever column the backend marks as time as a label", () => {
    render(
      <ResultTable
        analysis={analysis({ columns: ["survey_year", "gross_monthly_median"], rows: [[2019, 4200]], time_columns: ["survey_year"] })}
      />,
    );

    expect(cells()).toEqual(["2019", (4200).toLocaleString()]);
  });

  it("formats every number when a saved run has no time columns", () => {
    render(<ResultTable analysis={analysis({ time_columns: undefined })} />);

    expect(cells()).toEqual([(2020).toLocaleString(), (26110).toLocaleString()]);
  });
});
