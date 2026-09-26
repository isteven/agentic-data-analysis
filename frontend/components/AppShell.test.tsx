import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "@/components/AppShell";

const nav = vi.hoisted(() => ({ pathname: "/", push: vi.fn() }));

vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useRouter: () => ({ push: nav.push }),
}));
vi.mock("next/image", () => ({ default: () => null }));
vi.mock("@/lib/runs", () => ({ fetchAnalyses: vi.fn(async () => []) }));

beforeEach(() => {
  nav.pathname = "/";
  nav.push.mockReset();
});

function Counter() {
  const [n, setN] = useState(0);
  return <button onClick={() => setN(n + 1)}>clicked {n}</button>;
}

describe("AppShell", () => {
  it("keeps the sidebar as it was when the page inside changes", () => {
    const { rerender } = render(<AppShell><p>Chat page</p></AppShell>);
    fireEvent.click(screen.getByRole("button", { name: "Hide history" }));

    rerender(<AppShell><p>A past run</p></AppShell>);

    // Each page used to draw its own sidebar, so it reset (and reloaded) on navigation.
    expect(screen.getByRole("button", { name: "Show history" })).toBeInTheDocument();
  });

  it("New Chat on the chat page starts it afresh", () => {
    render(<AppShell><Counter /></AppShell>);
    fireEvent.click(screen.getByRole("button", { name: "clicked 0" }));

    fireEvent.click(screen.getByRole("button", { name: "New Chat" }));

    expect(screen.getByRole("button", { name: "clicked 0" })).toBeInTheDocument();
    expect(nav.push).not.toHaveBeenCalled();
  });

  it("New Chat on another page goes to the chat page", () => {
    nav.pathname = "/history/r1";
    render(<AppShell><p>A past run</p></AppShell>);

    fireEvent.click(screen.getByRole("button", { name: "New Chat" }));

    expect(nav.push).toHaveBeenCalledWith("/");
  });
});
