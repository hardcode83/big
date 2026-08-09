import { TechnicianShell } from "@/features/shell";
import { AuthGuard } from "@/features/auth";

export default function Layout({ children }: { children: React.ReactNode }) {
  return <TechnicianShell><AuthGuard>{children}</AuthGuard></TechnicianShell>;
}
