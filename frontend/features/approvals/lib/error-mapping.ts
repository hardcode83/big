import type { UseQueryResult } from "@tanstack/react-query";

import { ApiError } from "@/lib/api";

/**
 * A discriminated union of the UI states the approvals views need to render
 * (mirroring `IncidentsErrorState`, `features/incidents/lib/error-mapping.ts`).
 * The component picks the localized copy from the locale — this module
 * carries no UI strings, only the shape of the data.
 *
 * `"already-answered"` is the one addition beyond the incidents mirror: a
 * `409` from `useRespondOwnerApproval` — the backend's
 * `OwnerApprovalAlreadyAnsweredError` — maps here so the component can show
 * the translated "ya respondida" message and refetch, instead of leaving a
 * stale row on screen (R3.4).
 *
 * The `ok` variant is generic over the data type so the call site keeps the
 * typed DTO through to the consumer.
 */
export type ApprovalsErrorState<TData> =
  | { kind: "loading" }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "validation" }
  | { kind: "already-answered" }
  | { kind: "error" }
  | { kind: "ok"; data: TData };

/**
 * Map a TanStack Query/Mutation result to a discriminated UI state for the
 * approvals feature (R3.4). Pure mapper — no React hooks internally.
 *
 * The parameter shape (`isPending`/`isError`/`error`/`data`) is common to both
 * `UseQueryResult` (the queue/history reads) and `UseMutationResult` (the
 * owner's decision) in TanStack Query v5, so this one function serves both
 * call sites.
 *
 * Rules:
 * - `401`: delegated to the session-expiry flow. The view stays in
 *   `loading` so it does not flash a misleading variant while the refresh +
 *   redirect happen.
 * - `403`: forbidden.
 * - `404`: not-found.
 * - `409`: already-answered — the approval was answered elsewhere (another
 *   tab, another manager) between the row rendering and the owner's click.
 * - `422`: validation — the backend's envelope is **not** read, mapped, or
 *   exposed; the UI shows only the localized copy.
 * - `5xx` / `TypeError` (network): generic error.
 * - success: `ok` with the data.
 */
export function mapApprovalsError<TData, TError = Error>(
  result: Pick<
    UseQueryResult<TData, TError>,
    "isPending" | "isError" | "error" | "data"
  >,
): ApprovalsErrorState<TData> {
  if (result.isPending) {
    return { kind: "loading" };
  }
  if (result.isError) {
    const error = result.error as TError;
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
      if (error.status === 409) {
        return { kind: "already-answered" };
      }
      if (error.status === 422) {
        return { kind: "validation" };
      }
    }
    return { kind: "error" };
  }
  return { kind: "ok", data: result.data as TData };
}
