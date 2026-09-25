import Link from "next/link";

/** Full-width app bar above both the history sidebar and the main pane. */
export function AppHeader({ children }: { children?: React.ReactNode }) {
  return (
    <header className="flex shrink-0 items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
      <Link href="/" className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
        Policy Data Analytics
      </Link>
      {children}
    </header>
  );
}
