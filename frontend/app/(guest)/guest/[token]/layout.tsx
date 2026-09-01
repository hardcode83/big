import { GuestShell } from "@/features/shell/server";

export default function Layout({ children }: { children: React.ReactNode }) {
  return <GuestShell>{children}</GuestShell>;
}
