"use client";

import { useRef, useState } from "react";
import { AgentTrace } from "@/components/AgentTrace";
import { Markdown } from "@/components/Markdown";
import { hasChart, ResultChart } from "@/components/ResultChart";
import { ResultTable } from "@/components/ResultTable";
import { TokenUsage } from "@/components/TokenUsage";
import { exportChartAsPdf, exportChartAsPng, exportTableAsCsv } from "@/lib/export";
import type { ChatTurn, QueryResponse } from "@/lib/types";
import styles from "./ChatMessage.module.css";

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

type TabId = "report" | "data" | "steps" | "tokens";

interface Tab {
  id: TabId;
  label: string;
}

/** Only tabs with content; a failed run may have steps but no report, chart or data. */
function availableTabs(result: QueryResponse, withChart: boolean): Tab[] {
  const tabs: Tab[] = [];
  if (withChart || result.report_markdown) tabs.push({ id: "report", label: "Report" });
  if (result.analysis && result.analysis.columns.length > 0) {
    tabs.push({ id: "data", label: `Data (${result.analysis.rows.length})` });
  }
  if (result.trace.length > 0) tabs.push({ id: "steps", label: `Agent steps (${result.trace.length})` });
  if (result.token_usage && result.token_usage.calls > 0) tabs.push({ id: "tokens", label: "Token usage" });
  return tabs;
}

/** Exported for reuse on the history detail view, outside the chat-bubble layout. */
export function ResultTabs({ query, result }: { query: string; result: QueryResponse }) {
  const withChart = hasChart(result.analysis);
  const tabs = availableTabs(result, withChart);
  const [active, setActive] = useState<TabId | undefined>(tabs[0]?.id);
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
      <div className={styles.tabBar}>
        <div role="tablist" className={styles.tabList}>
          {tabs.map((tab) => (
            <button
              key={tab.id}
              role="tab"
              aria-selected={active === tab.id}
              onClick={() => setActive(tab.id)}
              className={active === tab.id ? `${styles.tab} ${styles.tabActive}` : styles.tab}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>
      <div role="tabpanel" className={styles.tabPanel}>
        {active === "report" && withChart && (
          <div className={styles.exportActions}>
            {(["png", "pdf"] as const).map((format) => (
              <button
                key={format}
                onClick={() => downloadChart(format)}
                disabled={exporting}
                className={styles.exportButton}
              >
                {exporting ? "Exporting…" : `Export ${format.toUpperCase()}`}
              </button>
            ))}
          </div>
        )}
        {active === "data" && result.analysis && (
          <div className={styles.exportActions}>
            <button
              onClick={() => exportTableAsCsv(result.analysis!, `${baseName}-data.csv`)}
              className={styles.exportButton}
            >
              Export CSV
            </button>
          </div>
        )}
        {active === "report" && (
          <div className={styles.report}>
            {withChart && result.analysis && <ResultChart ref={chartRef} analysis={result.analysis} />}
            {result.report_markdown && <Markdown>{result.report_markdown}</Markdown>}
          </div>
        )}
        {active === "data" && result.analysis && <ResultTable analysis={result.analysis} />}
        {active === "steps" && <AgentTrace steps={result.trace} />}
        {active === "tokens" && result.token_usage && <TokenUsage usage={result.token_usage} />}
      </div>
    </div>
  );
}

export function ChatMessage({ turn }: { turn: ChatTurn }) {
  return (
    <div className={styles.turn}>
      <div className={styles.question}>
        <div className={styles.questionBubble}>{turn.query}</div>
      </div>

      <div className={styles.answer}>
        <div className={styles.avatar}>AI</div>
        <div className={styles.answerBody}>
          {turn.pending && (
            <div className={styles.pending}>
              <p className={styles.pendingLabel}>
                <span className={styles.liveDot} />
                {turn.liveSteps.length === 0
                  ? "Starting the agents…"
                  : `Agents working… (${turn.liveSteps.length} step${turn.liveSteps.length === 1 ? "" : "s"})`}
              </p>
              <AgentTrace steps={turn.liveSteps} live />
            </div>
          )}
          {turn.error && (
            <p className={styles.error}>{turn.error}</p>
          )}
          {turn.result && (
            <>
              {STATUS_NOTES[turn.result.status] && (
                <p className={styles.statusNote}>
                  {STATUS_NOTES[turn.result.status]}
                </p>
              )}
              <ResultTabs query={turn.query} result={turn.result} />
              {turn.result.provider_used && (
                <p className={styles.providerNote}>
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
