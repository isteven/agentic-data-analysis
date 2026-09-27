"use client";

import { useEffect, useRef, useState } from "react";
import { ChatMessage } from "@/components/ChatMessage";
import { Composer } from "@/components/Composer";
import { useShell } from "@/components/AppShell";
import { API_URL, submitQuery, watchRun } from "@/lib/runs";
import type { ChatTurn, ProvidersInfo } from "@/lib/types";
import shared from "@/components/shared.module.css";
import styles from "./page.module.css";

const SUGGESTIONS = [
  "How did retrenchment of residents and non-residents change since 2015?",
  "Which university had the highest graduate employment rate in 2023?",
  "How did the share of women working 60+ hours change from 2023 to 2025?",
  "Which MRT stations have the shortest travel time to junior colleges?",
];

export default function Home() {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [draft, setDraft] = useState("");
  const [providers, setProviders] = useState<ProvidersInfo | null>(null);
  const [provider, setProvider] = useState<string>("");
  // History re-fetches when a question is submitted and when it finishes: a running
  // question shows at once, and again when it's done.
  const { refreshHistory } = useShell();
  // The run being watched; New Chat or leaving the page stops watching it.
  const watching = useRef<AbortController | null>(null);
  // One question per chat: each run is answered on its own (no follow-up context yet),
  // so the prompt box goes as soon as the question is asked; New Chat starts the next one.
  const asked = turns.length > 0;

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_URL}/api/health/providers`, { signal: controller.signal })
      .then((res) => (res.ok ? (res.json() as Promise<ProvidersInfo>) : Promise.reject(res.status)))
      .then((info) => {
        setProviders(info);
        setProvider(info.default);
      })
      // Without the list the picker is hidden and the server default is used.
      .catch((err) => {
        if (!controller.signal.aborted) console.error(`[DEBUG] ${new Date().toISOString()} providers fetch failed`, err);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => () => watching.current?.abort(), []);

  async function ask(query: string) {
    const id = crypto.randomUUID();
    setDraft("");
    setTurns((prev) => [...prev, { id, query, pending: true, liveSteps: [] }]);
    const patch = (fn: (t: ChatTurn) => Partial<ChatTurn>) =>
      setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, ...fn(t) } : t)));
    const controller = new AbortController();
    watching.current = controller;

    try {
      const { run_id } = await submitQuery(query, provider);
      refreshHistory();
      const result = await watchRun(run_id, (step) => patch((t) => ({ liveSteps: [...t.liveSteps, step] })), {
        signal: controller.signal,
      });
      patch(() => ({ result, pending: false }));
    } catch (err) {
      if (controller.signal.aborted) return; // New Chat or left the page: nothing to show
      console.error(`[DEBUG] ${new Date().toISOString()} ask failed`, { query, err });
      patch(() => ({ pending: false, error: err instanceof Error ? err.message : "Something went wrong" }));
    } finally {
      if (watching.current === controller) watching.current = null;
      refreshHistory();
    }
  }

  return (
    <div className={styles.main}>
      <main className={styles.scroll}>
        {turns.length === 0 ? (
          <div className={`${shared.column} ${styles.welcome}`}>
            <h2 className={styles.welcomeTitle}>What would you like to analyse?</h2>
            <p className={styles.welcomeSubtitle}>
              Singapore government datasets from data.gov.sg and MOM.
            </p>
            <div className={styles.suggestions}>
              {SUGGESTIONS.map((s) => (
                <button key={s} onClick={() => ask(s)} className={styles.suggestion}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className={`${shared.column} ${styles.turns}`}>
            {turns.map((t) => (
              <ChatMessage key={t.id} turn={t} />
            ))}
          </div>
        )}
      </main>

      <div className={`${shared.column} ${styles.composer}`}>
        {!asked && (
          <Composer
            value={draft}
            onChange={setDraft}
            onSubmit={() => ask(draft.trim())}
            disabled={asked}
            providers={providers}
            provider={provider}
            onProviderChange={setProvider}
          />
        )}
        <p className={styles.footnote}>
          AI can make mistakes. Please double-check responses.
        </p>
      </div>
    </div>
  );
}
