export interface TraceStep {
  node_name: string;
  step_type: "reasoning" | "action" | "observation" | string;
  content: string;
}

export interface QueryResponse {
  run_id: string;
  query_text: string;
  status: string;
  provider_used: string | null;
  report_markdown: string | null;
  trace: TraceStep[];
  analysis: Analysis | null;
  token_usage: TokenUsage | null; // null while running, or for runs before tracking
}

/** One LLM attempt, with the token counts its provider reported. */
export interface LlmCall {
  node_name: string;
  tier: string;
  provider: string;
  model: string | null;
  input_tokens: number; // includes cached_input_tokens
  output_tokens: number;
  cached_input_tokens: number;
  latency_ms: number;
  outcome: "ok" | "failed" | string;
}

export interface ModelUsage {
  provider: string;
  model: string | null;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cached_input_tokens: number;
}

/** Totals per model only: different models' tokens aren't comparable. */
export interface TokenUsage {
  calls: number;
  failed_calls: number;
  by_model: ModelUsage[];
  per_call: LlmCall[];
}

export interface ChartSpec {
  type: "line" | "bar" | "none" | string;
  x: string | null;
  y: string[];
  group: string | null;
  limit: number | null; // draw only the first N rows (too many categories); null = all
  sort: "asc" | "desc" | null; // by the first y column before cutting to limit; null = query order
  source: "planner" | "fallback" | string | null;
}

export type Cell = string | number | boolean | null;

/** The database-computed result the report and chart are drawn from. */
export interface Analysis {
  status: string;
  interpretation: string | null;
  sql: string | null;
  columns: string[];
  rows: Cell[][];
  truncated: boolean;
  reason: string | null;
  chart: ChartSpec | null;
}

/** One question and its answer in the chat; pending until the run finishes. */
export interface ChatTurn {
  id: string;
  query: string;
  pending: boolean;
  liveSteps: TraceStep[]; // streamed while pending; replaced by result.trace when done
  result?: QueryResponse;
  error?: string;
}

/** GET /api/health/providers: which LLM providers the backend has configured. */
export interface ProvidersInfo {
  default: string;
  providers: Record<string, { enabled: boolean }>;
}

/** One row of GET /api/analyses. */
export interface AnalysisSummary {
  run_id: string;
  query_text: string;
  status: string;
  provider_used: string | null;
  created_at: string;
  completed_at: string | null;
}
