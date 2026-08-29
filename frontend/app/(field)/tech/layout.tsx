import { TechnicianShell } from "@/features/shell/server";
import { AuthGuard } from "@/features/auth";

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <TechnicianShell>
      <AuthGuard allow={["TECHNICIAN"]}>{children}</AuthGuard>
    </TechnicianShell>
  );
}