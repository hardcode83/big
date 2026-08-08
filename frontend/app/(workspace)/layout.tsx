import { WorkspaceShell } from "@/features/shell";
import { AuthGuard } from "@/features/auth";

export default function Layout({ children }: { children: React.ReactNode }) {
  return <WorkspaceShell><AuthGuard>{children}</AuthGuard></WorkspaceShell>;
}
