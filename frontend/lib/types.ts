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
}
