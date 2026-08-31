import type { Metadata } from "next";

import { routeMetadata } from "@/features/shell/server";
import { GuestPortalView } from "@/features/guest-portal";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("guest");
}

export default async function Page({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <GuestPortalView token={token} />;
}
