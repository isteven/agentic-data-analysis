"use client";

import { useEffect, useRef, useState } from "react";
import { ChatMessage } from "@/components/ChatMessage";
import { Composer } from "@/components/Composer";
import type { ChatTurn, QueryResponse } from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const SUGGESTIONS = [
  "How did retrenchment of residents and non-residents change since 2015?",
  "Which university had the highest graduate employment rate in 2023?",
  "How did the share of women working 60+ hours change from 2023 to 2025?",
  "Which MRT stations have the shortest travel time to junior colleges?",
];

export default function Home() {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [draft, setDraft] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const busy = turns.some((t) => t.pending);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  async function ask(query: string) {
    const id = crypto.randomUUID();
    setDraft("");
    setTurns((prev) => [...prev, { id, query, pending: true }]);
    const update = (patch: Partial<ChatTurn>) =>
      setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, ...patch, pending: false } : t)));

    try {
      const res = await fetch(`${API_URL}/api/queries`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });
      if (!res.ok) throw new Error(`Request failed with status ${res.status}`);
      update({ result: (await res.json()) as QueryResponse });
    } catch (err) {
      console.error(`[DEBUG] ${new Date().toISOString()} ask failed`, { query, err });
      update({ error: err instanceof Error ? err.message : "Something went wrong" });
    }
  }

  return (
    <div className="flex h-screen flex-col bg-white dark:bg-zinc-950">
      <header className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <h1 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
          Policy Data Analytics
        </h1>
        {turns.length > 0 && (
          <button
            onClick={() => setTurns([])}
            disabled={busy}
            className="rounded-lg border border-zinc-300 px-3 py-1 text-sm text-zinc-700 hover:bg-zinc-100 disabled:opacity-40 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
          >
            New chat
          </button>
        )}
      </header>

      <main className="flex-1 overflow-y-auto">
        {turns.length === 0 ? (
          <div className="mx-auto flex h-full max-w-3xl flex-col items-center justify-center px-4">
            <h2 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100">
              What would you like to analyse?
            </h2>
            <p className="mt-2 text-sm text-zinc-500">
              Singapore government datasets from data.gov.sg and MOM.
            </p>
            <div className="mt-8 grid w-full gap-2 sm:grid-cols-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => ask(s)}
                  className="rounded-xl border border-zinc-200 px-4 py-3 text-left text-sm text-zinc-700 hover:bg-zinc-50 dark:border-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-900"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto max-w-3xl space-y-10 px-4 py-8">
            {turns.map((t) => (
              <ChatMessage key={t.id} turn={t} />
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </main>

      <div className="mx-auto w-full max-w-3xl px-4 pb-4">
        <Composer value={draft} onChange={setDraft} onSubmit={() => ask(draft.trim())} disabled={busy} />
        <p className="mt-2 text-center text-xs text-zinc-400">
          Every number is computed by the database and checked against the report.
        </p>
      </div>
    </div>
  );
}
