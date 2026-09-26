import Image from "next/image";
import Link from "next/link";
import logo from "@/app/logo.webp";
import styles from "./AppHeader.module.css";

interface Props {
  /** On the chat page: clears the conversation. A link to "/" can't, because
   *  navigating to the page you're on keeps its state. Elsewhere it's a link. */
  onNewChat?: () => void;
}

/** Full-width app bar above both the history sidebar and the main pane. */
export function AppHeader({ onNewChat }: Props) {
  return (
    <header className={styles.header}>
      <Link href="/" className={styles.title}>
        <Image src={logo} alt="" className={styles.logo} priority />
        <span className={styles.titleOnly}>POLICY DATA ANALYTICS</span>
      </Link>
      {onNewChat ? (
        <button onClick={onNewChat} className={styles.outlineButton}>
          New Chat
        </button>
      ) : (
        <Link href="/" className={styles.outlineButton}>
          New Chat
        </Link>
      )}
    </header>
  );
}
