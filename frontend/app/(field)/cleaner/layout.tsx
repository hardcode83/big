import { CleanerShell } from "@/features/shell";

export default function Layout({ children }: { children: React.ReactNode }) {
  return <CleanerShell>{children}</CleanerShell>;
}
