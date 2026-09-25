import type { Analysis } from "@/lib/types";

const format = (value: unknown) =>
  typeof value === "number"
    ? value.toLocaleString(undefined, { maximumFractionDigits: 2 })
    : value === null
      ? "—"
      : String(value);

/** The query result exactly as the database returned it, with the SQL that produced it. */
export function ResultTable({ analysis }: { analysis: Analysis }) {
  if (analysis.columns.length === 0) return null;

  return (
    <details className="mt-4 rounded border border-zinc-200 bg-white text-sm dark:border-zinc-800 dark:bg-zinc-900" open>
      <summary className="cursor-pointer px-4 py-2 font-medium text-zinc-700 dark:text-zinc-300">
        Data ({analysis.rows.length} row{analysis.rows.length === 1 ? "" : "s"}
        {analysis.truncated ? ", truncated" : ""})
      </summary>
      <div className="max-h-80 overflow-auto px-4 pb-4">
        <table className="w-full border-collapse text-left">
          <thead>
            <tr>
              {analysis.columns.map((c) => (
                <th key={c} className="border-b border-zinc-200 py-1 pr-4 font-medium text-zinc-600 dark:border-zinc-700 dark:text-zinc-400">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {analysis.rows.map((row, r) => (
              <tr key={r}>
                {row.map((cell, i) => (
                  <td
                    key={i}
                    className={`border-b border-zinc-100 py-1 pr-4 text-zinc-800 dark:border-zinc-800 dark:text-zinc-200 ${typeof cell === "number" ? "tabular-nums" : ""}`}
                  >
                    {format(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {analysis.sql && (
          <pre className="mt-3 whitespace-pre-wrap text-xs text-zinc-500 dark:text-zinc-400">{analysis.sql}</pre>
        )}
      </div>
    </details>
  );
}
