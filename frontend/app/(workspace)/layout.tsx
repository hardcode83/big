import { WorkspaceShell } from "@/features/shell";
import { AuthGuard } from "@/features/auth";

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard allow={["TENANT_OWNER", "PROPERTY_MANAGER"]}>
      <WorkspaceShell>{children}</WorkspaceShell>
    </AuthGuard>
  );
}