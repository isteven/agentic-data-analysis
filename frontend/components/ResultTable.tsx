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
    <div className="text-sm">
      {analysis.truncated && (
        <p className="mb-2 text-xs text-amber-700 dark:text-amber-300">Result truncated at {analysis.rows.length} rows.</p>
      )}
      <div className="max-h-96 overflow-auto">
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
    </div>
  );
}
