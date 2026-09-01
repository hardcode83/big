import type { Metadata } from "next";

import { CleaningView } from "@/features/cleaning";
import { routeMetadata } from "@/features/shell/server";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("cleaning");
}

export default function Page() {
  return <CleaningView />;
}
