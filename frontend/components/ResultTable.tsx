import type { Analysis } from "@/lib/types";
import styles from "./ResultTable.module.css";

const format = (value: unknown, isTime: boolean) =>
  typeof value === "number" && !isTime
    ? value.toLocaleString(undefined, { maximumFractionDigits: 2 })
    : value === null
      ? "—"
      : String(value);

/** The query result exactly as the database returned it, with the SQL that produced it. */
export function ResultTable({ analysis }: { analysis: Analysis }) {
  if (analysis.columns.length === 0) return null;
  // A year is a label, not a quantity: 2020, never 2,020.
  const timeColumns = new Set(analysis.time_columns ?? []);
  const isTime = analysis.columns.map((c) => timeColumns.has(c));

  return (
    <div className={styles.wrapper}>
      {analysis.truncated && (
        <p className={styles.truncated}>Result truncated at {analysis.rows.length} rows.</p>
      )}
      <div className={styles.scroll}>
        <table className={styles.table}>
          <thead>
            <tr>
              {analysis.columns.map((c) => (
                <th key={c} className={styles.th}>
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
                    className={typeof cell === "number" && !isTime[i] ? `${styles.td} ${styles.number}` : styles.td}
                  >
                    {format(cell, isTime[i])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {analysis.sql && <pre className={styles.sql}>{analysis.sql}</pre>}
      </div>
    </div>
  );
}
