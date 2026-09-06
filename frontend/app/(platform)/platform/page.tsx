import type { Metadata } from "next";

import { PlatformConsole } from "@/features/platform";
import { routeMetadata } from "@/features/shell/server";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("platform");
}

export default function Page() {
  return <PlatformConsole />;
}
