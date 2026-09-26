import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { watchRun } from "@/lib/runs";
import type { QueryResponse } from "@/lib/types";

/** Stands in for the browser's EventSource: the test drives its events. */
class FakeEventSource {
  static last: FakeEventSource;
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {};
  onerror: ((e: Event) => void) | null = null;
  closed = false;

  constructor(public url: string) {
    FakeEventSource.last = this;
  }
  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(fn);
  }
  close() {
    this.closed = true;
  }
  emit(type: string, data = "") {
    for (const fn of this.listeners[type] ?? []) fn({ data } as MessageEvent);
  }
}

const run = (status: string) => ({ run_id: "r1", status }) as QueryResponse;
const TIMINGS = { silenceMs: 1_000, timeoutMs: 10_000, pollIntervalMs: 100 };

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("EventSource", FakeEventSource);
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

function respondWith(...statuses: string[]) {
  for (const s of statuses) fetchMock.mockResolvedValueOnce({ ok: true, json: async () => run(s) });
}

describe("watchRun", () => {
  it("passes steps on and resolves with the saved result when the stream says done", async () => {
    respondWith("completed");
    const steps: unknown[] = [];

    const done = watchRun("r1", (s) => steps.push(s), { signal: new AbortController().signal, ...TIMINGS });
    FakeEventSource.last.emit("trace", JSON.stringify({ node_name: "intent", step_type: "action", content: "x" }));
    FakeEventSource.last.emit("done", "completed");

    await expect(done).resolves.toMatchObject({ status: "completed" });
    expect(steps).toHaveLength(1);
    expect(FakeEventSource.last.closed).toBe(true);
  });

  it("falls back to polling when the stream fails", async () => {
    respondWith("running", "completed");

    const done = watchRun("r1", () => {}, { signal: new AbortController().signal, ...TIMINGS });
    FakeEventSource.last.onerror?.(new Event("error"));
    await vi.advanceTimersByTimeAsync(TIMINGS.pollIntervalMs);

    await expect(done).resolves.toMatchObject({ status: "completed" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("switches to polling when the stream goes silent", async () => {
    respondWith("completed");

    const done = watchRun("r1", () => {}, { signal: new AbortController().signal, ...TIMINGS });
    await vi.advanceTimersByTimeAsync(TIMINGS.silenceMs);

    await expect(done).resolves.toMatchObject({ status: "completed" });
    expect(FakeEventSource.last.closed).toBe(true);
  });

  it("gives up with a clear error when the run never finishes", async () => {
    fetchMock.mockResolvedValue({ ok: true, json: async () => run("running") });

    const done = watchRun("r1", () => {}, { signal: new AbortController().signal, ...TIMINGS });
    const outcome = expect(done).rejects.toThrow(/taking too long/);
    await vi.advanceTimersByTimeAsync(TIMINGS.timeoutMs + TIMINGS.pollIntervalMs);

    await outcome;
  });

  it("stops watching when cancelled: stream closed, no more requests", async () => {
    const controller = new AbortController();

    const done = watchRun("r1", () => {}, { signal: controller.signal, ...TIMINGS });
    const outcome = expect(done).rejects.toMatchObject({ name: "AbortError" });
    controller.abort();
    await outcome;
    await vi.advanceTimersByTimeAsync(TIMINGS.timeoutMs);

    expect(FakeEventSource.last.closed).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
