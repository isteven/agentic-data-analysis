import Image from "next/image";
import Link from "next/link";
import logo from "@/app/logo.png";
import styles from "./AppHeader.module.css";

/** Full-width app bar above both the history sidebar and the main pane. New Chat is
 *  handled by the shell (components/AppShell.tsx): a plain link to "/" can't reset the
 *  chat page it's already on. */
export function AppHeader({ onNewChat }: { onNewChat: () => void }) {
  return (
    <header className={styles.header}>
      <Link href="/" className={styles.title}>
        <Image src={logo} alt="" className={styles.logo} priority />
        <span className={styles.titleOnly}>POLICY DATA ANALYTICS</span>
      </Link>
      <button onClick={onNewChat} className={styles.outlineButton}>
        New Chat
      </button>
    </header>
  );
}
