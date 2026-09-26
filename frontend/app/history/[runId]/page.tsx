"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { ResultTabs } from "@/components/ChatMessage";
import { AppHeader } from "@/components/AppHeader";
import { HistorySidebar } from "@/components/HistorySidebar";
import { fetchRun } from "@/lib/runs";
import type { QueryResponse } from "@/lib/types";
import shared from "@/components/shared.module.css";
import styles from "../history.module.css";

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
    <div className={shared.shell}>
      <AppHeader />
      <div className={shared.shellBody}>
        <HistorySidebar />

        <div className={styles.detailScroll}>
          <div className={`${shared.column} ${styles.detail}`}>
            <br />
            {/* <Link href="/" className={styles.backLink}>
              ← Back
            </Link> */}
            {error && <p className={`${shared.error} ${styles.spaced}`}>{error}</p>}
            {!error && !result && <p className={`${shared.muted} ${styles.spaced}`}>Loading…</p>}

            {result && (
              <>
                <h1 className={`${shared.pageTitle} ${styles.detailTitle}`}>{result.query_text}</h1>
                <ResultTabs query={result.query_text} result={result} />
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
