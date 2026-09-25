"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { fetchAnalyses } from "@/lib/runs";
import type { AnalysisSummary } from "@/lib/types";

const STATUS_DOT: Record<string, string> = {
  completed: "bg-emerald-500",
  partial: "bg-amber-500",
  failed: "bg-red-500",
  running: "bg-blue-500",
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/**
 * Persistent left rail of past questions (Claude-sidebar-style), collapsible.
 * Each item links to the read-only /history/{runId} detail page - there's no
 * resumable "session" concept yet (see project-management.md's M2.3), so this
 * lists individual past questions rather than grouped conversations.
 */
export function HistorySidebar({ refreshKey }: { refreshKey?: unknown }) {
  const [runs, setRuns] = useState<AnalysisSummary[] | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    fetchAnalyses()
      .then(setRuns)
      .catch((err) => console.error(`[DEBUG] ${new Date().toISOString()} sidebar history fetch failed`, err));
  }, [refreshKey]);

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        aria-label="Show history"
        title="Show history"
        className="flex w-10 shrink-0 items-start justify-center border-r border-zinc-200 pt-4 text-zinc-400 hover:text-zinc-700 dark:border-zinc-800 dark:hover:text-zinc-200"
      >
        <ChevronIcon direction="right" />
      </button>
    );
  }

  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-zinc-200 dark:border-zinc-800">
      <div className="flex items-center justify-between px-3 py-3">
        <span className="text-xs font-semibold uppercase tracking-wide text-zinc-500">History</span>
        <button
          onClick={() => setCollapsed(true)}
          aria-label="Hide history"
          title="Hide history"
          className="text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200"
        >
          <ChevronIcon direction="left" />
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-2 pb-3">
        {runs === null && <p className="px-2 py-2 text-xs text-zinc-400">Loading…</p>}
        {runs?.length === 0 && <p className="px-2 py-2 text-xs text-zinc-400">No questions yet.</p>}
        <ul className="space-y-0.5">
          {runs?.map((run) => {
            const href = `/history/${run.run_id}`;
            const active = pathname === href;
            return (
              <li key={run.run_id}>
                <Link
                  href={href}
                  title={run.query_text}
                  className={`flex items-start gap-2 rounded-lg px-2 py-1.5 text-sm ${
                    active
                      ? "bg-zinc-100 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100"
                      : "text-zinc-600 hover:bg-zinc-50 dark:text-zinc-400 dark:hover:bg-zinc-900"
                  }`}
                >
                  <span
                    className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${STATUS_DOT[run.status] ?? "bg-zinc-400"}`}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{run.query_text}</span>
                    <span className="block text-xs text-zinc-400">{formatDate(run.created_at)}</span>
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </aside>
  );
}

function ChevronIcon({ direction }: { direction: "left" | "right" }) {
  return (
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2.5}>
      <path
        d={direction === "left" ? "M15 19l-7-7 7-7" : "M9 5l7 7-7 7"}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
