import type { Metadata } from "next";

import { routeMetadata } from "@/features/shell/server";
import { RoutePlaceholder } from "@/features/shell/components/route-placeholder";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("cleaner-task");
}

export default function Page() {
  return <RoutePlaceholder routeId="cleaner-task" />;
}
