import type { Metadata } from "next";

import { IncidentsView } from "@/features/incidents";
import { routeMetadata } from "@/features/shell/server";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("incidents");
}

export default function Page() {
  return <IncidentsView />;
}