import type { Metadata } from "next";

import { routeMetadata } from "@/features/shell/server";
import { ApprovalsView } from "@/features/approvals/components/approvals-view";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("approvals");
}

export default function Page() {
  return <ApprovalsView />;
}
