import { GuestShell } from "@/features/shell";

export default function Layout({ children }: { children: React.ReactNode }) {
  return <GuestShell>{children}</GuestShell>;
}
