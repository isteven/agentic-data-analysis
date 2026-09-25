"use client";

import { useEffect, useRef } from "react";
import type { TraceStep } from "@/lib/types";

const STEP_TYPE_STYLES: Record<string, string> = {
  reasoning: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
  action: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
  observation: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200",
};

function stepBadgeClass(stepType: string): string {
  return (
    STEP_TYPE_STYLES[stepType] ??
    "bg-zinc-100 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200"
  );
}

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
    <ol
      ref={listRef}
      className={`divide-y divide-zinc-100 overflow-y-auto dark:divide-zinc-800 ${live ? "max-h-72" : "max-h-[32rem]"}`}
    >
      {steps.map((step, i) => (
        <li
          key={i}
          className={`py-3 first:pt-0 ${live && i === steps.length - 1 ? "animate-pulse" : ""}`}
        >
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
              {step.node_name}
            </span>
            <span
              className={`rounded px-2 py-0.5 text-xs font-medium ${stepBadgeClass(step.step_type)}`}
            >
              {step.step_type}
            </span>
          </div>
          <p className="mt-1 text-sm text-zinc-800 dark:text-zinc-200">{step.content}</p>
        </li>
      ))}
    </ol>
  );
}
