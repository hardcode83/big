import { PublicShell } from "@/features/shell/server";

export default function Layout({ children }: { children: React.ReactNode }) {
  return <PublicShell>{children}</PublicShell>;
}
