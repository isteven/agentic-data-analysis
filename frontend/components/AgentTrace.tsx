"use client";

import { useEffect, useRef } from "react";
import { Badge } from "@/components/Badge";
import type { TraceStep } from "@/lib/types";
import styles from "./AgentTrace.module.css";

/** `live`: steps are still arriving - keep the newest in view and mark it as current. */
export function AgentTrace({ steps, live = false }: { steps: TraceStep[]; live?: boolean }) {
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    if (live && listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [live, steps.length]);

  if (steps.length === 0) {
    return null;
  }

  return (
    <ol ref={listRef} className={live ? `${styles.list} ${styles.live}` : styles.list}>
      {steps.map((step, i) => (
        <li
          key={i}
          className={live && i === steps.length - 1 ? `${styles.step} ${styles.current}` : styles.step}
        >
          <div className={styles.stepHeader}>
            <span className={styles.node}>{step.node_name}</span>
            <Badge>{step.step_type}</Badge>
          </div>
          <p className={styles.content}>{step.content}</p>
        </li>
      ))}
    </ol>
  );
}
