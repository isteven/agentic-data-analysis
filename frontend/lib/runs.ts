import type { AnalysisSummary, QueryResponse, TraceStep } from "@/lib/types";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TERMINAL = new Set(["completed", "partial", "failed"]);

export interface WatchOptions {
  /** Cancels watching: the stream is closed and polling stops (the run itself goes on). */
  signal: AbortSignal;
  /** No stream event for this long: assume the stream is stuck and poll instead. */
  silenceMs?: number;
  /** Give up on the run after this long in total. The worker ends a run after 180 s. */
  timeoutMs?: number;
  pollIntervalMs?: number;
}

const DEFAULTS = { silenceMs: 45_000, timeoutMs: 5 * 60_000, pollIntervalMs: 2_000 };

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

/** GET /api/analyses: past runs, most recent first. */
export async function fetchAnalyses(signal?: AbortSignal): Promise<AnalysisSummary[]> {
  const res = await fetch(`${API_URL}/api/analyses`, { signal });
  if (!res.ok) throw new Error(`Fetching history failed (HTTP ${res.status})`);
  const data: { runs: AnalysisSummary[] } = await res.json();
  return data.runs;
}

export async function fetchRun(runId: string, signal?: AbortSignal): Promise<QueryResponse> {
  const res = await fetch(`${API_URL}/api/queries/${runId}`, { signal });
  if (!res.ok) throw new Error(`Fetching the result failed (HTTP ${res.status})`);
  return res.json();
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(signal.reason);
    }, { once: true });
  });
}

async function pollUntilDone(runId: string, signal: AbortSignal, deadline: number, intervalMs: number) {
  while (Date.now() < deadline) {
    const run = await fetchRun(runId, signal);
    if (TERMINAL.has(run.status)) return run;
    await sleep(intervalMs, signal);
  }
  throw new Error("The analysis is taking too long; try again later.");
}

/**
 * Streams a run's agent steps (SSE) and resolves with the finished result.
 * If the stream fails or goes silent, falls back to polling; after `timeoutMs` in total
 * it gives up, so a question can't stay "running" forever. The browser's own
 * auto-reconnect is disabled on purpose: the server replays the stream from the start,
 * so a reconnect would repeat every step.
 */
export function watchRun(
  runId: string,
  onStep: (step: TraceStep) => void,
  options: WatchOptions,
): Promise<QueryResponse> {
  const { signal, silenceMs, timeoutMs, pollIntervalMs } = { ...DEFAULTS, ...options };
  const deadline = Date.now() + timeoutMs;

  return new Promise((resolve, reject) => {
    if (signal.aborted) return reject(signal.reason);
    const source = new EventSource(`${API_URL}/api/agent-trace/${runId}`);
    let finished = false;
    let silence: ReturnType<typeof setTimeout> | undefined;
    const armSilence = () => {
      clearTimeout(silence);
      silence = setTimeout(() => {
        log("trace stream silent, polling instead", { runId, silenceMs });
        finish(true);
      }, silenceMs);
    };
    const stop = () => {
      finished = true;
      clearTimeout(silence);
      source.close();
    };
    const finish = (fromPolling: boolean) => {
      if (finished) return;
      stop();
      (fromPolling ? pollUntilDone(runId, signal, deadline, pollIntervalMs) : fetchRun(runId, signal)).then(
        resolve,
        reject,
      );
    };

    signal.addEventListener("abort", () => {
      stop();
      reject(signal.reason);
    }, { once: true });
    source.addEventListener("trace", (e) => {
      armSilence();
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
    armSilence();
  });
}
