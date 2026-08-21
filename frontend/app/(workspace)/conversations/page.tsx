import { Suspense } from "react";
import type { Metadata } from "next";

import { LoadingState } from "@/components/states";
import { ConversationsView } from "@/features/conversations";
import { routeMetadata } from "@/features/shell";
import { getServerT } from "@/lib/i18n/server";

export function generateMetadata(): Promise<Metadata> {
  return routeMetadata("conversations");
}

/**
 * The `<Suspense>` boundary is load-bearing, not decoration (design D5):
 * `ConversationsView` calls `useSearchParams()`, which makes Next bail out of
 * prerendering, and the boundary is what keeps that bail-out scoped to the subtree
 * instead of the whole route.
 *
 * It does **not** currently decide whether `next build` passes, and the earlier
 * wording here claimed it did: every page awaits `getServerT()` below, which reads
 * `cookies()`, so this route — like all 24 — is already dynamic and the build has no
 * static path to reject. Verified by removing the boundary and building: it still
 * compiles. So the boundary's guarantee is scoping today and correctness the day
 * server i18n stops being a per-request dependency; what actually guards its removal
 * is `app/error-architecture.test.ts`, not R7.5's build step.
 *
 * The fallback copy is resolved on the server, so the boundary ships no client i18n
 * of its own.
 */
export default async function Page() {
  const t = await getServerT();
  return (
    <Suspense fallback={<LoadingState label={t("conversations:inbox.loading")} />}>
      <ConversationsView />
    </Suspense>
  );
}
