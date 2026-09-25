"use client";

import { useRef, useState } from "react";
import { AgentTrace } from "@/components/AgentTrace";
import { Markdown } from "@/components/Markdown";
import { hasChart, ResultChart } from "@/components/ResultChart";
import { ResultTable } from "@/components/ResultTable";
import { exportChartAsPdf, exportChartAsPng, exportTableAsCsv } from "@/lib/export";
import type { ChatTurn, QueryResponse } from "@/lib/types";

/** A short, filesystem-safe name for downloads, derived from the question. */
function slugify(text: string): string {
  return (
    text
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || "analysis"
  );
}

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

/** Exported for reuse on the history detail view, outside the chat-bubble layout. */
export function ResultTabs({ query, result }: { query: string; result: QueryResponse }) {
  const tabs = availableTabs(result);
  // Chart first when there is one (the visual answer), else the report.
  const [active, setActive] = useState<TabId | undefined>(
    tabs.find((t) => t.id === "chart")?.id ?? tabs.find((t) => t.id === "report")?.id ?? tabs[0]?.id,
  );
  const [exporting, setExporting] = useState(false);
  const chartRef = useRef<HTMLDivElement>(null);
  const baseName = slugify(query);
  if (tabs.length === 0) return null;

  async function downloadChart(format: "png" | "pdf") {
    const node = chartRef.current;
    if (!node) return;
    setExporting(true);
    try {
      if (format === "png") await exportChartAsPng(node, `${baseName}-chart.png`);
      else await exportChartAsPdf(node, `${baseName}-chart.pdf`, query);
    } catch (err) {
      console.error(`[DEBUG] ${new Date().toISOString()} chart export failed`, err);
    } finally {
      setExporting(false);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between">
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
        {active === "chart" && (
          <div className="flex shrink-0 gap-3">
            {(["png", "pdf"] as const).map((format) => (
              <button
                key={format}
                onClick={() => downloadChart(format)}
                disabled={exporting}
                className="whitespace-nowrap text-xs font-medium text-zinc-500 hover:text-zinc-800 disabled:opacity-40 dark:hover:text-zinc-200"
              >
                {exporting ? "Exporting…" : `Export ${format.toUpperCase()}`}
              </button>
            ))}
          </div>
        )}
        {active === "data" && result.analysis && (
          <button
            onClick={() => exportTableAsCsv(result.analysis!, `${baseName}-data.csv`)}
            className="shrink-0 whitespace-nowrap text-xs font-medium text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
          >
            Export CSV
          </button>
        )}
      </div>
      <div role="tabpanel" className="pt-4">
        {active === "report" && result.report_markdown && <Markdown>{result.report_markdown}</Markdown>}
        {active === "steps" && <AgentTrace steps={result.trace} />}
        {active === "chart" && result.analysis && <ResultChart ref={chartRef} analysis={result.analysis} />}
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
            <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
              <p className="mb-2 flex items-center gap-2 text-sm text-zinc-500">
                <span className="h-2 w-2 animate-ping rounded-full bg-blue-500" />
                {turn.liveSteps.length === 0
                  ? "Starting the agents…"
                  : `Agents working… (${turn.liveSteps.length} step${turn.liveSteps.length === 1 ? "" : "s"})`}
              </p>
              <AgentTrace steps={turn.liveSteps} live />
            </div>
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
              <ResultTabs query={turn.query} result={turn.result} />
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
