import type { Metadata } from "next";

import { PricingView } from "@/features/pricing";
import { routeMetadata } from "@/features/shell/server";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("pricing");
}

export default function Page() {
  return <PricingView />;
}
