import type { Metadata } from "next";

import { routeMetadata } from "@/features/shell/server";
import { CleanerTaskListView } from "@/features/cleaner";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("cleaner");
}

export default function Page() {
  return <CleanerTaskListView />;
}