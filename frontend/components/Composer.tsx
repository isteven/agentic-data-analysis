"use client";

import { useEffect, useRef } from "react";

interface Props {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  disabled: boolean;
}

/** Auto-growing prompt box: Enter sends, Shift+Enter adds a line. */
export function Composer({ value, onChange, onSubmit, disabled }: Props) {
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
      className="flex items-end gap-2 rounded-3xl border border-zinc-300 bg-white px-4 py-2 shadow-sm focus-within:border-zinc-400 dark:border-zinc-700 dark:bg-zinc-900"
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
        className="max-h-[200px] flex-1 resize-none bg-transparent py-1.5 text-[15px] text-zinc-900 outline-none placeholder:text-zinc-400 dark:text-zinc-100"
      />
      <button
        type="submit"
        disabled={!canSend}
        aria-label="Send"
        className="mb-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-black text-white disabled:opacity-30 dark:bg-white dark:text-black"
      >
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2.5}>
          <path d="M12 19V5M5 12l7-7 7 7" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
    </form>
  );
}
