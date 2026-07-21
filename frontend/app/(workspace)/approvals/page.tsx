import type { Metadata } from "next";

import { routeMetadata } from "@/features/shell";
import { RoutePlaceholder } from "@/features/shell/components/route-placeholder";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("approvals");
}

export default function Page() {
  return <RoutePlaceholder routeId="approvals" />;
}
