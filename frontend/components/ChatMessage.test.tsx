import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ResultTabs } from "@/components/ChatMessage";
import type { QueryResponse } from "@/lib/types";

function response(overrides: Partial<QueryResponse> = {}): QueryResponse {
  return {
    run_id: "run-1",
    query_text: "How many residents were retrenched in 2020?",
    status: "completed",
    provider_used: "openai",
    report_markdown: "14,380 residents were retrenched in 2020.",
    trace: [{ node_name: "intent", step_type: "action", content: "Interpreted as: ..." }],
    analysis: {
      status: "answered",
      interpretation: "Residents retrenched in 2020",
      sql: "SELECT year, retrench_resident FROM data.retrenchment WHERE year = 2020",
      columns: ["year", "retrench_resident"],
      rows: [[2020, 14380]],
      truncated: false,
      reason: null,
      chart: { type: "bar", x: "year", y: ["retrench_resident"], group: null, limit: null, sort: null, source: "planner" },
    },
    token_usage: {
      calls: 1,
      failed_calls: 0,
      by_model: [{ provider: "openai", model: "gpt-4o", calls: 1, input_tokens: 700, output_tokens: 30, cached_input_tokens: 0 }],
      per_call: [],
    },
    ...overrides,
  };
}

const tabNames = () => screen.getAllByRole("tab").map((t) => t.textContent);

describe("ResultTabs", () => {
  it("shows Report, Data, Agent steps and Token usage, opening on Report", () => {
    render(<ResultTabs query="q" result={response()} />);

    expect(tabNames()).toEqual(["Report", "Data (1)", "Agent steps (1)", "Token usage"]);
    expect(screen.getByRole("tab", { name: "Report" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("14,380 residents were retrenched in 2020.")).toBeInTheDocument();
  });

  it("has no Token usage tab for a run from before usage was recorded", () => {
    render(<ResultTabs query="q" result={response({ token_usage: null })} />);

    expect(tabNames()).not.toContain("Token usage");
  });

  it("shows only the agent steps for a run that failed before answering", () => {
    render(<ResultTabs query="q" result={response({ status: "failed", report_markdown: null, analysis: null, token_usage: null })} />);

    expect(tabNames()).toEqual(["Agent steps (1)"]);
  });

  it("offers CSV export on the Data tab and chart export on the Report tab", () => {
    render(<ResultTabs query="q" result={response()} />);

    expect(screen.getByRole("button", { name: "Export PNG" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Export CSV" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Data (1)" }));

    expect(screen.getByRole("button", { name: "Export CSV" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Export PNG" })).not.toBeInTheDocument();
  });
});
