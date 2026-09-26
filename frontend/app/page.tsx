"use client";

import { useEffect, useRef, useState } from "react";
import { ChatMessage } from "@/components/ChatMessage";
import { Composer } from "@/components/Composer";
import { AppHeader } from "@/components/AppHeader";
import { HistorySidebar } from "@/components/HistorySidebar";
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
  const bottomRef = useRef<HTMLDivElement>(null);
  const busy = turns.some((t) => t.pending);
  // Bumped whenever a turn finishes, so the sidebar re-fetches and shows the new entry.
  const completedCount = turns.filter((t) => t.result || t.error).length;

  useEffect(() => {
    fetch(`${API_URL}/api/health/providers`)
      .then((res) => (res.ok ? (res.json() as Promise<ProvidersInfo>) : Promise.reject(res.status)))
      .then((info) => {
        setProviders(info);
        setProvider(info.default);
      })
      // Without the list the picker is hidden and the server default is used.
      .catch((err) => console.error(`[DEBUG] ${new Date().toISOString()} providers fetch failed`, err));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  async function ask(query: string) {
    const id = crypto.randomUUID();
    setDraft("");
    setTurns((prev) => [...prev, { id, query, pending: true, liveSteps: [] }]);
    const patch = (fn: (t: ChatTurn) => Partial<ChatTurn>) =>
      setTurns((prev) => prev.map((t) => (t.id === id ? { ...t, ...fn(t) } : t)));

    try {
      const { run_id } = await submitQuery(query, provider);
      const result = await watchRun(run_id, (step) => patch((t) => ({ liveSteps: [...t.liveSteps, step] })));
      patch(() => ({ result, pending: false }));
    } catch (err) {
      console.error(`[DEBUG] ${new Date().toISOString()} ask failed`, { query, err });
      patch(() => ({ pending: false, error: err instanceof Error ? err.message : "Something went wrong" }));
    }
  }

  return (
    <div className={shared.shell}>
      <AppHeader onNewChat={() => setTurns([])} newChatDisabled={busy} />

      <div className={shared.shellBody}>
        <HistorySidebar refreshKey={completedCount} />

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
                <div ref={bottomRef} />
              </div>
            )}
          </main>

          <div className={`${shared.column} ${styles.composer}`}>
            <Composer
              value={draft}
              onChange={setDraft}
              onSubmit={() => ask(draft.trim())}
              disabled={busy}
              providers={providers}
              provider={provider}
              onProviderChange={setProvider}
            />
            <p className={styles.footnote}>
              AI can make mistakes. Please double-check responses.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
