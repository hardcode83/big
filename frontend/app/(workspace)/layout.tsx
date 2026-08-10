import { WorkspaceShell } from "@/features/shell";
import { AuthGuard } from "@/features/auth";

export default function Layout({ children }: { children: React.ReactNode }) {
  return <AuthGuard><WorkspaceShell>{children}</WorkspaceShell></AuthGuard>;
}
