import { Badge } from "@/components/Badge";
import type { TokenUsage as Usage } from "@/lib/types";
import styles from "./TokenUsage.module.css";

const count = (n: number) => n.toLocaleString();
const seconds = (ms: number) => `${(ms / 1000).toFixed(1)} s`;

const NUMBER_COLUMNS = ["Input", "Cached input", "Output"];

/** Token counts per model and per LLM call, as each provider reported them. Totals
 *  stay per model: models tokenize differently, so their tokens don't add up. */
export function TokenUsage({ usage }: { usage: Usage }) {
  return (
    <div className={styles.wrapper}>
      <p className={styles.note}>
        Counts as reported by each provider. Input includes cached input.
        {usage.failed_calls > 0 &&
          ` ${usage.failed_calls} failed attempt${usage.failed_calls === 1 ? "" : "s"} (retried or given up).`}
      </p>

      <section>
        <h3 className={styles.heading}>Totals by model</h3>
        <div className={styles.scroll}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th className={styles.th}>Model</th>
                <th className={`${styles.th} ${styles.number}`}>Calls</th>
                {NUMBER_COLUMNS.map((c) => (
                  <th key={c} className={`${styles.th} ${styles.number}`}>
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {usage.by_model.map((m) => (
                <tr key={`${m.provider}/${m.model}`}>
                  <td className={styles.td}>
                    {m.model ?? "unknown"} <span className={styles.model}>({m.provider})</span>
                  </td>
                  <td className={`${styles.td} ${styles.number}`}>{m.calls}</td>
                  <td className={`${styles.td} ${styles.number}`}>{count(m.input_tokens)}</td>
                  <td className={`${styles.td} ${styles.number}`}>{count(m.cached_input_tokens)}</td>
                  <td className={`${styles.td} ${styles.number}`}>{count(m.output_tokens)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h3 className={styles.heading}>Each call ({usage.calls})</h3>
        <div className={styles.scroll}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th className={`${styles.th} ${styles.number}`}>#</th>
                <th className={styles.th}>Step</th>
                <th className={styles.th}>Model</th>
                {NUMBER_COLUMNS.map((c) => (
                  <th key={c} className={`${styles.th} ${styles.number}`}>
                    {c}
                  </th>
                ))}
                <th className={`${styles.th} ${styles.number}`}>Time</th>
              </tr>
            </thead>
            <tbody>
              {usage.per_call.map((c, i) => (
                <tr key={i}>
                  <td className={`${styles.td} ${styles.number}`}>{i + 1}</td>
                  <td className={styles.td}>
                    <span className={styles.step}>
                      {c.node_name}
                      {c.outcome !== "ok" && <Badge tone="red">{c.outcome}</Badge>}
                    </span>
                  </td>
                  <td className={`${styles.td} ${styles.model}`}>{c.model ?? c.provider}</td>
                  <td className={`${styles.td} ${styles.number}`}>{count(c.input_tokens)}</td>
                  <td className={`${styles.td} ${styles.number}`}>{count(c.cached_input_tokens)}</td>
                  <td className={`${styles.td} ${styles.number}`}>{count(c.output_tokens)}</td>
                  <td className={`${styles.td} ${styles.number}`}>{seconds(c.latency_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
