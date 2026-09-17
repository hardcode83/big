import type { Metadata } from "next";

import { StatementsPage } from "@/features/statements";
import { routeMetadata } from "@/features/shell/server";

/**
 * `/statements` route — task 6.3.
 *
 * The route was a `RoutePlaceholder` through sections 1-5 of this change
 * while the feature surface was built. Now that the feature's view is real,
 * this file is again a thin server composition: `routeMetadata` for SEO +
 * `generateMetadata` (consumed by Next's metadata API), and the entry
 * component from the feature's public barrel. The workspace `layout.tsx`
 * already gates the route behind `AuthGuard allow={["TENANT_OWNER",
 * "PROPERTY_MANAGER"]}`; we add no new permission check or guard here, in
 * line with R1, D6 and the proposal's explicit "no new auth routes" rule.
 */
export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("statements");
}

export default function Page() {
  return <StatementsPage />;
}
