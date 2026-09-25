"use client";

import { useState } from "react";
import { AgentTrace } from "@/components/AgentTrace";
import { Markdown } from "@/components/Markdown";
import { hasChart, ResultChart } from "@/components/ResultChart";
import { ResultTable } from "@/components/ResultTable";
import type { ChatTurn, QueryResponse } from "@/lib/types";

const STATUS_NOTES: Record<string, string> = {
  partial: "Partial answer — see the agent steps for what could not be answered.",
  failed: "The run failed — see the agent steps for details.",
};

type TabId = "report" | "steps" | "chart" | "data";

interface Tab {
  id: TabId;
  label: string;
}

/** Only tabs with content; a failed run may have steps but no report, chart or data. */
function availableTabs(result: QueryResponse): Tab[] {
  const tabs: Tab[] = [];
  if (result.report_markdown) tabs.push({ id: "report", label: "Report" });
  if (result.trace.length > 0) tabs.push({ id: "steps", label: `Agent steps (${result.trace.length})` });
  if (hasChart(result.analysis)) tabs.push({ id: "chart", label: "Chart" });
  if (result.analysis && result.analysis.columns.length > 0) {
    tabs.push({ id: "data", label: `Data (${result.analysis.rows.length})` });
  }
  return tabs;
}

function ResultTabs({ result }: { result: QueryResponse }) {
  const tabs = availableTabs(result);
  const [active, setActive] = useState<TabId | undefined>(tabs[0]?.id);
  if (tabs.length === 0) return null;

  return (
    <div>
      <div
        role="tablist"
        className="flex h-10 items-stretch gap-1 overflow-x-auto overflow-y-hidden border-b border-zinc-200 dark:border-zinc-800"
      >
        {tabs.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={active === tab.id}
            onClick={() => setActive(tab.id)}
            className={`-mb-px flex shrink-0 items-center whitespace-nowrap border-b-2 px-3 text-sm font-medium leading-none ${
              active === tab.id
                ? "border-zinc-900 text-zinc-900 dark:border-zinc-100 dark:text-zinc-100"
                : "border-transparent text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="pt-4">
        {active === "report" && result.report_markdown && <Markdown>{result.report_markdown}</Markdown>}
        {active === "steps" && <AgentTrace steps={result.trace} />}
        {active === "chart" && result.analysis && <ResultChart analysis={result.analysis} />}
        {active === "data" && result.analysis && <ResultTable analysis={result.analysis} />}
      </div>
    </div>
  );
}

export function ChatMessage({ turn }: { turn: ChatTurn }) {
  return (
    <div className="space-y-6">
      <div className="flex justify-end">
        <div className="max-w-[80%] whitespace-pre-wrap rounded-3xl bg-zinc-100 px-5 py-2.5 text-[15px] text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100">
          {turn.query}
        </div>
      </div>

      <div className="flex gap-3">
        <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-zinc-300 text-xs font-semibold text-zinc-600 dark:border-zinc-700 dark:text-zinc-300">
          AI
        </div>
        <div className="min-w-0 flex-1">
          {turn.pending && (
            <p className="animate-pulse pt-1 text-sm text-zinc-500">
              Agents are analysing the data…
            </p>
          )}
          {turn.error && (
            <p className="pt-1 text-sm text-red-600 dark:text-red-400">{turn.error}</p>
          )}
          {turn.result && (
            <>
              {STATUS_NOTES[turn.result.status] && (
                <p className="mb-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-950 dark:text-amber-200">
                  {STATUS_NOTES[turn.result.status]}
                </p>
              )}
              <ResultTabs result={turn.result} />
              {turn.result.provider_used && (
                <p className="mt-3 text-xs text-zinc-400">
                  {turn.result.provider_used.includes("->")
                    ? `Provider fallback: ${turn.result.provider_used}`
                    : `Answered by ${turn.result.provider_used}`}
                </p>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
