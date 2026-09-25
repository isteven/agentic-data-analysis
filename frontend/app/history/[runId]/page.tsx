"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { ResultTabs } from "@/components/ChatMessage";
import { HistorySidebar } from "@/components/HistorySidebar";
import { fetchRun } from "@/lib/runs";
import type { QueryResponse } from "@/lib/types";

export default function HistoryDetailPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = use(params);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchRun(runId)
      .then(setResult)
      .catch((err) => {
        console.error(`[DEBUG] ${new Date().toISOString()} run fetch failed`, { runId, err });
        setError(err instanceof Error ? err.message : "Something went wrong");
      });
  }, [runId]);

  return (
    <div className="flex h-screen bg-white dark:bg-zinc-950">
      <HistorySidebar />

      <div className="min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl px-4 py-8">
          <Link href="/" className="text-sm text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200">
            ← New chat
          </Link>

          {error && <p className="mt-4 text-sm text-red-600 dark:text-red-400">{error}</p>}
          {!error && !result && <p className="mt-4 text-sm text-zinc-500">Loading…</p>}

          {result && (
            <>
              <h1 className="mt-4 mb-6 text-lg font-semibold text-zinc-900 dark:text-zinc-100">
                {result.query_text}
              </h1>
              <ResultTabs query={result.query_text} result={result} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
