import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TokenUsage } from "@/components/TokenUsage";
import type { LlmCall, TokenUsage as Usage } from "@/lib/types";

function call(node_name: string, overrides: Partial<LlmCall> = {}): LlmCall {
  return {
    node_name,
    tier: "quality",
    provider: "openai",
    model: "gpt-4o",
    input_tokens: 1200,
    output_tokens: 80,
    cached_input_tokens: 1024,
    latency_ms: 1500,
    outcome: "ok",
    ...overrides,
  };
}

const usage: Usage = {
  calls: 3,
  failed_calls: 1,
  by_model: [
    { provider: "openai", model: "gpt-4o", calls: 2, input_tokens: 1200, output_tokens: 80, cached_input_tokens: 1024 },
    { provider: "bedrock", model: "claude-haiku-4-5", calls: 1, input_tokens: 900, output_tokens: 60, cached_input_tokens: 0 },
  ],
  per_call: [
    call("intent"),
    call("coordinator", { input_tokens: 0, output_tokens: 0, cached_input_tokens: 0, outcome: "failed" }),
    call("coordinator", { provider: "bedrock", model: "claude-haiku-4-5", input_tokens: 900, output_tokens: 60, cached_input_tokens: 0 }),
  ],
};

describe("TokenUsage", () => {
  it("totals per model, never a grand total across models", () => {
    render(<TokenUsage usage={usage} />);

    const [totals] = screen.getAllByRole("table");
    const rows = within(totals).getAllByRole("row").slice(1);
    expect(rows.map((r) => r.textContent)).toEqual([
      "gpt-4o (openai)21,2001,02480",
      "claude-haiku-4-5 (bedrock)1900060",
    ]);
  });

  it("lists each call in order and marks a failed attempt", () => {
    render(<TokenUsage usage={usage} />);

    const [, calls] = screen.getAllByRole("table");
    const rows = within(calls).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(within(rows[1]).getByText("failed")).toBeInTheDocument();
    expect(within(rows[2]).queryByText("failed")).not.toBeInTheDocument();
    expect(screen.getByText(/1 failed attempt/)).toBeInTheDocument();
  });
});
