import type { Metadata } from "next";

import { routeMetadata } from "@/features/shell/server";
import { TenantSettingsView } from "@/features/tenant-settings";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("settings");
}

export default function Page() {
  return <TenantSettingsView />;
}
