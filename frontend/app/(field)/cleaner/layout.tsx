import { CleanerShell } from "@/features/shell/server";
import { AuthGuard } from "@/features/auth";

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <CleanerShell>
      <AuthGuard allow={["CLEANER"]}>{children}</AuthGuard>
    </CleanerShell>
  );
}