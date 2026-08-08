import type { Metadata } from "next";

import { routeMetadata } from "@/features/shell";
import { LoginForm } from "@/features/auth";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("login");
}

export default function Page() {
  return <LoginForm />;
}
