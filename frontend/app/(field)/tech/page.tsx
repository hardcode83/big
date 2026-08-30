import type { Metadata } from "next";

import { routeMetadata } from "@/features/shell/server";
import { TechIncidentsView } from "@/features/tech";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("tech");
}

export default function Page() {
  return <TechIncidentsView />;
}
