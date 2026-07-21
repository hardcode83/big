import { TechnicianShell } from "@/features/shell";

export default function Layout({ children }: { children: React.ReactNode }) {
  return <TechnicianShell>{children}</TechnicianShell>;
}
