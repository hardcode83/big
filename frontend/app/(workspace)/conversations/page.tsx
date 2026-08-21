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
 * `ConversationsView` calls `useSearchParams()`, and with `output: "standalone"`
 * and no `force-dynamic`, a prerenderable route that reads the search params
 * without a suspense boundary fails `next build` — which R7.5 requires to pass
 * with no backend running. The fallback copy is resolved on the server, so the
 * boundary ships no client i18n of its own.
 */
export default async function Page() {
  const t = await getServerT();
  return (
    <Suspense fallback={<LoadingState label={t("conversations:inbox.loading")} />}>
      <ConversationsView />
    </Suspense>
  );
}
