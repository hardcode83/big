import type { Metadata } from "next";

import { DashboardView } from "@/features/dashboard";
import { routeMetadata } from "@/features/shell";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("dashboard");
}

export default function Page() {
  return <DashboardView />;
}
