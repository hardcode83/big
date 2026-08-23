import type { Metadata } from "next";

import { PropertiesView } from "@/features/properties";
import { routeMetadata } from "@/features/shell";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("properties");
}

export default function Page() {
  return <PropertiesView />;
}
