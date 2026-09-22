"use client";

import { useState } from "react";
import { AgentTrace } from "@/components/AgentTrace";
import type { QueryResponse } from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function Home() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const res = await fetch(`${API_URL}/api/queries`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });
      if (!res.ok) {
        throw new Error(`Request failed with status ${res.status}`);
      }
      const data: QueryResponse = await res.json();
      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-black">
      <main className="mx-auto max-w-2xl px-6 py-16">
        <h1 className="text-2xl font-semibold text-black dark:text-zinc-50">
          Agentic Policy Data Analytics Platform
        </h1>
        <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
          Ask a question about employment, retrenchment, or job vacancy data.
        </p>

        <form onSubmit={handleSubmit} className="mt-8 flex gap-2">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. What were retrenchment trends in manufacturing?"
            className="flex-1 rounded border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-50"
            required
          />
          <button
            type="submit"
            disabled={loading}
            className="rounded bg-black px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-50 dark:text-black"
          >
            {loading ? "Running..." : "Submit"}
          </button>
        </form>

        {error && (
          <p className="mt-6 text-sm text-red-600 dark:text-red-400">{error}</p>
        )}

        {result && (
          <>
            <pre className="mt-6 whitespace-pre-wrap rounded border border-zinc-200 bg-white p-4 text-sm text-zinc-800 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200">
              {result.report_markdown ?? JSON.stringify(result, null, 2)}
            </pre>
            <AgentTrace steps={result.trace} />
          </>
        )}
      </main>
    </div>
  );
}
