import Image from "next/image";
import Link from "next/link";
import logo from "@/app/logo.webp";
import styles from "./AppHeader.module.css";

/** Full-width app bar above both the history sidebar and the main pane. */
export function AppHeader({ children }: { children?: React.ReactNode }) {
  return (
    <header className={styles.header}>
      <Link href="/" className={styles.title}>
        <Image src={logo} alt="" className={styles.logo} priority />
        <span className={styles.titleOnly}>
            POLICY DATA ANALYTICS
            </span>
      </Link>
      {children}
      {<Link href="/" className={styles.outlineButton}>
        New Chat
      </Link>}
    </header>
  );
}
