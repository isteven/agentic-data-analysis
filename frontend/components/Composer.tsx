"use client";

import { useEffect, useRef } from "react";
import type { ProvidersInfo } from "@/lib/types";
import styles from "./Composer.module.css";

const PROVIDER_LABELS: Record<string, string> = { openai: "OpenAI", bedrock: "AWS Bedrock" };

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled: boolean;
  providers: ProvidersInfo | null;
  provider: string;
  onProviderChange: (provider: string) => void;
}

/** Auto-growing prompt box: Enter sends, Shift+Enter adds a line. */
export function Composer({
  value,
  onChange,
  onSubmit,
  disabled,
  providers,
  provider,
  onProviderChange,
}: Props) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  const canSend = !disabled && value.trim().length > 0;

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (canSend) onSubmit();
      }}
      className={styles.form}
    >
      <textarea
        ref={ref}
        rows={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          // isComposing: don't send mid-IME input (e.g. Chinese pinyin).
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            if (canSend) onSubmit();
          }
        }}
        placeholder="Ask about retrenchment, working hours, graduate employment…"
        className={styles.input}
      />
      {providers && (
        <select
          value={provider}
          onChange={(e) => onProviderChange(e.target.value)}
          aria-label="LLM provider"
          title="LLM provider; another configured provider takes over if this one fails"
          className={styles.providerSelect}
        >
          {Object.entries(providers.providers).map(([name, { enabled }]) => (
            <option key={name} value={name} disabled={!enabled}>
              {PROVIDER_LABELS[name] ?? name}
              {enabled ? "" : " (not configured)"}
            </option>
          ))}
        </select>
      )}
      <button
        type="submit"
        disabled={!canSend}
        aria-label="Send"
        className={styles.send}
      >
        <svg viewBox="0 0 24 24" className={styles.sendIcon} fill="none" stroke="currentColor" strokeWidth={2.5}>
          <path d="M12 19V5M5 12l7-7 7 7" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
    </form>
  );
}
