"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, Fragment, useCallback, useContext, useMemo, useState } from "react";
import { AppHeader } from "@/components/AppHeader";
import { HistorySidebar } from "@/components/HistorySidebar";
import shared from "@/components/shared.module.css";

interface Shell {
  /** Re-fetch the History sidebar, e.g. when a question is submitted or finishes. */
  refreshHistory: () => void;
}

const ShellContext = createContext<Shell>({ refreshHistory: () => {} });

export const useShell = () => useContext(ShellContext);

/**
 * Header and History sidebar around every page, rendered once by the (shell) layout.
 * Each page used to draw its own, so every navigation remounted the sidebar: its
 * collapsed state reset and History reloaded.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [historyVersion, setHistoryVersion] = useState(0);
  // Remounting the page is what starts a new chat: its state resets and its unmount
  // stops following any run in progress (the run itself finishes on the server).
  const [chatKey, setChatKey] = useState(0);

  const refreshHistory = useCallback(() => setHistoryVersion((v) => v + 1), []);
  const shell = useMemo(() => ({ refreshHistory }), [refreshHistory]);

  function newChat() {
    if (pathname === "/") setChatKey((k) => k + 1);
    else router.push("/");
  }

  return (
    <ShellContext.Provider value={shell}>
      <div className={shared.shell}>
        <AppHeader onNewChat={newChat} />
        <div className={shared.shellBody}>
          <HistorySidebar refreshKey={historyVersion} />
          <Fragment key={chatKey}>{children}</Fragment>
        </div>
      </div>
    </ShellContext.Provider>
  );
}
