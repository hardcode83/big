import type { UseQueryResult } from "@tanstack/react-query";

import { ApiError } from "@/lib/api";

/**
 * A discriminated union of the UI states `ManagerCleaningTaskMessagesPanel`
 * needs to render the thread read (proposal R2.5, design D5). The component
 * picks the localized copy from the `cleaning` namespace — this module
 * carries no UI strings, only the shape of the read state.
 *
 * Mirrors `IncidentsErrorState` in `features/incidents/lib/error-mapping.ts`,
 * the precedent the section-2 manager's `incidents` panel uses. The 401
 * branch keeps the mapper in `loading` so the auth flow owns session
 * expiration instead of flashing a misleading variant while the refresh +
 * redirect happen.
 */
export type CleaningMessagesState =
  | { kind: "loading" }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "validation" }
  | { kind: "error" }
  | { kind: "ok" };

/**
 * Map a TanStack Query **or** mutation result to a discriminated UI state for
 * the cleaning thread (R2.5, D5). Pure mapper — no React hooks internally.
 *
 * Rules (read):
 * - `401`: delegated to the session-expiry flow. The panel stays in
 *   `loading` so it does not flash a misleading variant while the refresh +
 *   redirect happen.
 * - `404`: not-found — the task itself is gone, fold into the parent's
 *   whole-screen EmptyState.
 * - `5xx` / `TypeError` (network) / unknown error: generic error.
 * - success: `ok`.
 *
 * Rules (send — same mapper, because TanStack mutation results expose the
 * same `isPending` / `isError` / `error` shape):
 * - `403`: forbidden — composer shows `messages.errors.forbidden`.
 * - `404`: not-found — composer shows `messages.errors.notFound`.
 * - `422`: validation — composer shows `messages.errors.tooLong` (R2.3
 *   length bound, the only one `POST .../messages` can raise client-side
 *   that the composer does not already pre-empt).
 * - anything else: generic.
 *
 * `mapCleaningDetailError` (the detail screen mapper) does not expose a
 * `forbidden` branch to its consumers either, but here the mapper has to
 * distinguish it because the send error copy is status-specific (R2.5).
 */
export function mapCleaningError<TData, TError = Error>(
  queryResult: Pick<
    UseQueryResult<TData, TError>,
    "isPending" | "isError" | "error"
  >,
): CleaningMessagesState {
  if (queryResult.isPending) {
    return { kind: "loading" };
  }
  if (queryResult.isError) {
    const error = queryResult.error as TError;
    if (error instanceof ApiError) {
      if (error.status === 401) {
        return { kind: "loading" };
      }
      if (error.status === 403) {
        return { kind: "forbidden" };
      }
      if (error.status === 404) {
        return { kind: "not-found" };
      }
      if (error.status === 422) {
        return { kind: "validation" };
      }
    }
    return { kind: "error" };
  }
  return { kind: "ok" };
}

/**
 * Map a failed send's `kind` to the copy the composer shows (R2.5).
 *
 * `validation` is the length `422`, the only one `POST .../messages` can
 * raise — its body carries a single field. `not-found` is the task having
 * disappeared between the read and the write. `forbidden` covers the case
 * where the manager's role was revoked mid-session. Anything else surfaces
 * the generic copy. `loading` (the `401` branch) is the auth flow's "stay
 * quiet"; for a failed send there is no such second chance, so it falls
 * through to the generic message rather than nothing at all.
 */
export function sendErrorKeyForCleaning(kind: string): string {
  if (kind === "validation") return "messages.errors.tooLong";
  if (kind === "not-found") return "messages.errors.notFound";
  if (kind === "forbidden") return "messages.errors.forbidden";
  return "messages.errors.generic";
}
