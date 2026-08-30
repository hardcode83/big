import type { QueryClient, QueryKey } from "@tanstack/react-query";

/**
 * Undo whatever the optimistic patch did to the unread counter, and nothing else.
 *
 * Three cases, and the first one is the one that matters most:
 *
 * - **The patch never touched the counter** (`patched === false`). Then the revert must be a
 *   no-op. `useMarkRead` only decrements when a row actually moved from unread to read AND it
 *   had a snapshot to decrement from, so this is its normal case — and an earlier version of
 *   this helper destroyed the counter query anyway, turning a correct no-op into a destructive
 *   operation on a query the mutation had not modified (typically the bell's first,
 *   still-unresolved load).
 * - **There was a snapshot.** Write it back.
 * - **There was no snapshot but the patch wrote anyway** — `useMarkAllRead` zeroes the counter
 *   unconditionally, including when it has just cancelled the first in-flight load. Writing
 *   `undefined` back does NOT clear an entry in TanStack v5 (an `undefined` updater result is
 *   a bail-out), so the honest revert is `resetQueries`: it clears the state **and** refetches
 *   the observers that are mounted. `removeQueries` was the first attempt and is not enough —
 *   it deletes the entry without re-pointing the attached observers, so a mounted bell would
 *   keep painting the optimistic zero until its next render or its next 60 s poll, and the
 *   `onSettled` invalidation would match nothing to heal it.
 *
 * Both refinements came from the section-5 security panel, the second on its re-review.
 */
export interface CountSnapshot {
  patched: boolean;
  previousCount: number | undefined;
}

export function restoreCount(
  queryClient: QueryClient,
  unreadKey: QueryKey,
  snapshot: CountSnapshot,
): void {
  if (!snapshot.patched) {
    return;
  }
  if (snapshot.previousCount === undefined) {
    void queryClient.resetQueries({ queryKey: unreadKey, exact: true });
    return;
  }
  queryClient.setQueryData<number>(unreadKey, snapshot.previousCount);
}
