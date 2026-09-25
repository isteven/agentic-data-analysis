"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fetchAnalyses } from "@/lib/runs";
import type { AnalysisSummary } from "@/lib/types";

const STATUS_STYLES: Record<string, string> = {
  completed: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200",
  partial: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  failed: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
  running: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
};

function statusClass(status: string): string {
  return STATUS_STYLES[status] ?? "bg-zinc-100 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200";
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export default function HistoryPage() {
  const [runs, setRuns] = useState<AnalysisSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAnalyses()
      .then(setRuns)
      .catch((err) => {
        console.error(`[DEBUG] ${new Date().toISOString()} history fetch failed`, err);
        setError(err instanceof Error ? err.message : "Something went wrong");
      });
  }, []);

  return (
    <div className="mx-auto min-h-screen max-w-3xl px-4 py-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-100">History</h1>
        <Link
          href="/"
          className="rounded-lg border border-zinc-300 px-3 py-1 text-sm text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
        >
          New chat
        </Link>
      </div>

      {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
      {!error && runs === null && <p className="text-sm text-zinc-500">Loading…</p>}
      {runs?.length === 0 && <p className="text-sm text-zinc-500">No questions asked yet.</p>}

      <ul className="divide-y divide-zinc-100 dark:divide-zinc-800">
        {runs?.map((run) => (
          <li key={run.run_id}>
            <Link
              href={`/history/${run.run_id}`}
              className="flex items-start justify-between gap-4 py-3 hover:bg-zinc-50 dark:hover:bg-zinc-900"
            >
              <div className="min-w-0">
                <p className="truncate text-sm text-zinc-900 dark:text-zinc-100">{run.query_text}</p>
                <p className="mt-1 text-xs text-zinc-500">
                  {formatDate(run.created_at)}
                  {run.provider_used ? ` · ${run.provider_used}` : ""}
                </p>
              </div>
              <span className={`shrink-0 rounded px-2 py-0.5 text-xs font-medium ${statusClass(run.status)}`}>
                {run.status}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
