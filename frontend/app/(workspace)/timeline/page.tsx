import type { Metadata } from "next";

import { TimelineView } from "@/features/dashboard";
import { routeMetadata } from "@/features/shell/server";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("timeline");
}

export default function Page() {
  return <TimelineView />;
}
