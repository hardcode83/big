import type { Metadata } from "next";

import { routeMetadata } from "@/features/shell/server";
import { RoutePlaceholder } from "@/features/shell/components/route-placeholder";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("tech");
}

export default function Page() {
  return <RoutePlaceholder routeId="tech" />;
}
