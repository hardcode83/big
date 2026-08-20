import type { UseQueryResult } from "@tanstack/react-query";

import { ApiError } from "@/lib/api";

/**
 * A discriminated union of the UI states the incidents views need to render.
 * The component picks the localized copy from the locale — this module carries
 * no UI strings, only the shape of the data (R5.4).
 *
 * The `ok` variant is generic over the data type so the call site keeps the
 * typed DTO through to the consumer — a rename of `IncidentList` or
 * `IncidentDetailDto` propagates and tsc catches the consumer without an
 * `as` cast.
 */
export type IncidentsErrorState<TData> =
  | { kind: "loading" }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "validation" }
  | { kind: "error" }
  | { kind: "ok"; data: TData };

/**
 * Map a TanStack Query result to a discriminated UI state for the incidents
 * feature (R5.4). Pure mapper — no React hooks internally.
 *
 * Rules:
 * - `401`: delegated to the session-expiry flow. The view stays in
 *   `loading` so it does not flash a misleading variant while the refresh +
 *   redirect happen.
 * - `403`: forbidden.
 * - `404`: not-found.
 * - `422`: validation — the backend's envelope is **not** read, mapped, or
 *   exposed; the UI shows only the localized copy.
 * - `5xx` / `TypeError` (network): generic error.
 * - success: `ok` with the data.
 */
export function mapIncidentsError<TData, TError = Error>(
  queryResult: Pick<UseQueryResult<TData, TError>, "isPending" | "isError" | "error" | "data">,
): IncidentsErrorState<TData> {
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
  return { kind: "ok", data: queryResult.data as TData };
}