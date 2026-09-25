export interface TraceStep {
  node_name: string;
  step_type: "reasoning" | "action" | "observation" | string;
  content: string;
}

export interface QueryResponse {
  run_id: string;
  status: string;
  provider_used: string | null;
  report_markdown: string | null;
  trace: TraceStep[];
  analysis: Analysis | null;
}

export interface ChartSpec {
  type: "line" | "bar" | "none" | string;
  x: string | null;
  y: string[];
  group: string | null;
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
