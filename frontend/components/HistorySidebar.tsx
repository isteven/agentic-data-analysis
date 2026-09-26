"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { fetchAnalyses } from "@/lib/runs";
import type { AnalysisSummary } from "@/lib/types";
import styles from "./HistorySidebar.module.css";

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
    // Aborted on the next refresh or unmount, so a slow earlier response can't
    // overwrite a newer one.
    const controller = new AbortController();
    fetchAnalyses(controller.signal)
      .then(setRuns)
      .catch((err) => {
        if (!controller.signal.aborted) console.error(`[DEBUG] ${new Date().toISOString()} sidebar history fetch failed`, err);
      });
    return () => controller.abort();
  }, [refreshKey]);

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        aria-label="Show history"
        title="Show history"
        className={styles.collapsed}
      >
        <ChevronIcon direction="right" />
      </button>
    );
  }

  return (
    <aside className={styles.sidebar}>
      <div className={styles.heading}>
        <div className={styles.headingLabel}>
          History
        </div>
        <button
          onClick={() => setCollapsed(true)}
          aria-label="Hide history"
          title="Hide history"
          className={styles.hideButton}
        >
          <ChevronIcon direction="left" />
        </button>
      </div>

      <nav className={styles.nav}>
        {runs === null && <p className={styles.message}>Loading…</p>}
        {runs?.length === 0 && <p className={styles.message}>No questions yet.</p>}
        <ul className={styles.list}>
          {runs?.map((run) => {
            const href = `/history/${run.run_id}`;
            const active = pathname === href;
            return (
              <li key={run.run_id}>
                <Link
                  href={href}
                  title={run.query_text}
                  className={active ? `${styles.item} ${styles.itemActive}` : styles.item}
                >
                  <span className={`${styles.dot} ${styles[run.status] ?? ""}`} />
                  <span className={styles.itemText}>
                    <span className={styles.itemQuery}>{run.query_text}</span>
                    <span className={styles.itemDate}>{formatDate(run.created_at)}</span>
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
    <svg viewBox="0 0 24 24" className={styles.chevron} fill="none" stroke="currentColor" strokeWidth={2.5}>
      <path
        d={direction === "left" ? "M15 19l-7-7 7-7" : "M9 5l7 7-7 7"}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
