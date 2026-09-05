import { getQueryClient } from "@/lib/query/query-client";
import { advanceSessionGeneration } from "./session-store";

/**
 * Empties the singleton `QueryClient` and advances `getSessionGeneration()` by
 * exactly 1, without touching tokens. The invariant — every purge invalidates
 * by construction any in-flight snapshots — is what the guards at
 * `features/notifications/hooks/use-mark-read.ts:109` and
 * `use-mark-all-read.ts:99` rely on: they compare `getSessionGeneration()`
 * against the value captured at `onMutate` and drop the optimistic rollback
 * whenever the session moved under the mutation. Adding a new purge path that
 * does not go through here reintroduces the hole.
 */
export function purgeSessionCache(): void {
  advanceSessionGeneration();
  getQueryClient().clear();
}
