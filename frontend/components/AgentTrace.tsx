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

export function AgentTrace({ steps }: { steps: TraceStep[] }) {
  if (steps.length === 0) {
    return null;
  }

  return (
    <details className="mt-4 rounded border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
      <summary className="cursor-pointer px-4 py-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
        Agent steps ({steps.length})
      </summary>
      <ol className="divide-y divide-zinc-100 border-t border-zinc-200 dark:divide-zinc-800 dark:border-zinc-800">
        {steps.map((step, i) => (
          <li key={i} className="px-4 py-3">
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
    </details>
  );
}
