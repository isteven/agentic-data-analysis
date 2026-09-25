import { AgentTrace } from "@/components/AgentTrace";
import { Markdown } from "@/components/Markdown";
import { ResultChart } from "@/components/ResultChart";
import { ResultTable } from "@/components/ResultTable";
import type { ChatTurn } from "@/lib/types";

const STATUS_NOTES: Record<string, string> = {
  partial: "Partial answer — see the agent steps for what could not be answered.",
  failed: "The run failed — see the agent steps for details.",
};

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
              {turn.result.report_markdown && <Markdown>{turn.result.report_markdown}</Markdown>}
              {turn.result.analysis && (
                <>
                  <ResultChart analysis={turn.result.analysis} />
                  <ResultTable analysis={turn.result.analysis} />
                </>
              )}
              <AgentTrace steps={turn.result.trace} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
