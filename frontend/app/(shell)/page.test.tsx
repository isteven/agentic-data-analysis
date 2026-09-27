import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Home from "@/app/(shell)/page";
import { AppShell } from "@/components/AppShell";

// The watched run never finishes on its own: the test decides what happens to it.
const watch = vi.hoisted(() => ({ signal: undefined as AbortSignal | undefined }));

vi.mock("@/lib/runs", () => ({
  API_URL: "http://api",
  submitQuery: vi.fn(async () => ({ run_id: "r1" })),
  fetchAnalyses: vi.fn(async () => []),
  watchRun: vi.fn((_runId: string, _onStep: unknown, options: { signal: AbortSignal }) => {
    watch.signal = options.signal;
    return new Promise(() => {});
  }),
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/", useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next/image", () => ({ default: () => null }));

beforeEach(() => {
  watch.signal = undefined;
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 503 })));
});

async function ask(question: string) {
  fireEvent.change(screen.getByPlaceholderText(/Ask about/), { target: { value: question } });
  await act(async () => {
    fireEvent.keyDown(screen.getByPlaceholderText(/Ask about/), { key: "Enter" });
  });
}

describe("Home: New Chat during a run", () => {
  it("is clickable while a question is running, and starts over", async () => {
    render(<AppShell><Home /></AppShell>);
    await ask("How many residents were retrenched in 2020?");

    expect(screen.getByText("How many residents were retrenched in 2020?")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/Ask about/)).not.toBeInTheDocument(); // one question per chat
    const newChat = screen.getByRole("button", { name: "New Chat" });
    expect(newChat).toBeEnabled();

    fireEvent.click(newChat);

    expect(screen.queryByText("How many residents were retrenched in 2020?")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Ask about/)).toBeInTheDocument();
    expect(watch.signal?.aborted).toBe(true); // stopped watching the abandoned run
  });

  it("stops watching the run when the page goes away", async () => {
    const { unmount } = render(<AppShell><Home /></AppShell>);
    await ask("How many residents were retrenched in 2020?");

    unmount();

    expect(watch.signal?.aborted).toBe(true);
  });
});
