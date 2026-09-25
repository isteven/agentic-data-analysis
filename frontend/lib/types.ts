export interface TraceStep {
  node_name: string;
  step_type: "reasoning" | "action" | "observation" | string;
  content: string;
}

export interface QueryResponse {
  run_id: string;
  status: string;
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
