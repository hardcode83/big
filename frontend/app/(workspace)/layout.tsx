import { WorkspaceShell } from "@/features/shell";

export default function Layout({ children }: { children: React.ReactNode }) {
  return <WorkspaceShell>{children}</WorkspaceShell>;
}
