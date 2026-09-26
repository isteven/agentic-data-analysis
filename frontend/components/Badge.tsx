import styles from "./Badge.module.css";

export type BadgeTone = "blue" | "amber" | "green" | "red" | "neutral";

/** Tone per run status and per trace step type; anything unknown is neutral. */
const TONES: Record<string, BadgeTone> = {
  completed: "green",
  partial: "amber",
  failed: "red",
  running: "blue",
  reasoning: "blue",
  action: "amber",
  observation: "green",
};

export function Badge({ children, tone }: { children: string; tone?: BadgeTone }) {
  return <span className={`${styles.badge} ${styles[tone ?? TONES[children] ?? "neutral"]}`}>{children}</span>;
}
