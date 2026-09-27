import { AppShell } from "@/components/AppShell";

/** Layouts persist across navigation, so the header and History sidebar render once. */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
