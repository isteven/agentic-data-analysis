"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Badge } from "@/components/Badge";
import shared from "@/components/shared.module.css";
import { fetchAnalyses } from "@/lib/runs";
import type { AnalysisSummary } from "@/lib/types";
import styles from "./history.module.css";

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
    <div className={`${shared.column} ${styles.listPage}`}>
      <div className={styles.listHeader}>
        <h1 className={shared.pageTitle}>History</h1>
        <Link href="/" className={shared.outlineButton}>
          New chat
        </Link>
      </div>

      {error && <p className={shared.error}>{error}</p>}
      {!error && runs === null && <p className={shared.muted}>Loading…</p>}
      {runs?.length === 0 && <p className={shared.muted}>No questions asked yet.</p>}

      <ul>
        {runs?.map((run) => (
          <li key={run.run_id} className={styles.runItem}>
            <Link href={`/history/${run.run_id}`} className={styles.run}>
              <div className={styles.runText}>
                <p className={styles.runQuery}>{run.query_text}</p>
                <p className={styles.runMeta}>
                  {formatDate(run.created_at)}
                  {run.provider_used ? ` · ${run.provider_used}` : ""}
                </p>
              </div>
              <Badge>{run.status}</Badge>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
