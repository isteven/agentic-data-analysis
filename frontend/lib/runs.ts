import type { QueryResponse, TraceStep } from "@/lib/types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TERMINAL = new Set(["completed", "partial", "failed"]);
const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 10 * 60 * 1000;

const log = (msg: string, ctx: unknown) =>
  console.error(`[DEBUG] ${new Date().toISOString()} ${msg}`, ctx);

/** POST /api/queries: starts the run on the worker and returns at once (status "running"). */
export async function submitQuery(query: string, provider?: string): Promise<QueryResponse> {
  const res = await fetch(`${API_URL}/api/queries`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, provider: provider || undefined }),
  });
  if (!res.ok) throw new Error(`Submitting the question failed (HTTP ${res.status})`);
  return res.json();
}

export async function fetchRun(runId: string): Promise<QueryResponse> {
  const res = await fetch(`${API_URL}/api/queries/${runId}`);
  if (!res.ok) throw new Error(`Fetching the result failed (HTTP ${res.status})`);
  return res.json();
}

async function pollUntilDone(runId: string): Promise<QueryResponse> {
  const deadline = Date.now() + POLL_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const run = await fetchRun(runId);
    if (TERMINAL.has(run.status)) return run;
    await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
  }
  throw new Error("The analysis is taking too long; try again later.");
}

/**
 * Streams a run's agent steps (SSE) and resolves with the finished result.
 * If the stream fails, falls back to polling. The browser's own auto-reconnect is
 * disabled on purpose: the server replays the stream from the start, so a reconnect
 * would repeat every step.
 */
export function watchRun(runId: string, onStep: (step: TraceStep) => void): Promise<QueryResponse> {
  return new Promise((resolve, reject) => {
    const source = new EventSource(`${API_URL}/api/agent-trace/${runId}`);
    let finished = false;
    const finish = (fromPolling: boolean) => {
      if (finished) return;
      finished = true;
      source.close();
      (fromPolling ? pollUntilDone(runId) : fetchRun(runId)).then(resolve, reject);
    };

    source.addEventListener("trace", (e) => {
      try {
        onStep(JSON.parse((e as MessageEvent).data));
      } catch (err) {
        log("bad trace event", { runId, data: (e as MessageEvent).data, err });
      }
    });
    source.addEventListener("done", () => finish(false));
    source.onerror = (err) => {
      log("trace stream failed, polling instead", { runId, err });
      finish(true);
    };
  });
}
