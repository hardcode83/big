import type { Metadata } from "next";

import { routeMetadata } from "@/features/shell";
import { RoutePlaceholder } from "@/features/shell/components/route-placeholder";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("forgot-password");
}

export default function Page() {
  return <RoutePlaceholder routeId="forgot-password" />;
}
