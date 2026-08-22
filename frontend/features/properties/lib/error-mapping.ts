import type { UseQueryResult } from "@tanstack/react-query";

import { ApiError } from "@/lib/api";

/**
 * A discriminated union of the UI states the properties list needs to render
 * (proposal R3). The component picks the localized copy from the locale — this
 * module carries no UI strings, only the shape of the data.
 *
 * `not-found` is part of the union to keep the shape identical to
 * `features/reservations`' mapper (design D8), but **this feature never
 * produces it**: see `mapPropertiesError` below.
 *
 * The reason is structural parity with that mapper, and nothing more. It is
 * explicitly NOT "reserved for a future per-property screen here": the
 * `/properties/[id]` detail already exists and is served by `PropertyDetailView`
 * from `features/dashboard`, and R5.2 forbids this feature from ever calling the
 * per-property endpoints that could produce a real 404. Keeping the variant buys
 * an identical union across the two mappers; it does not anticipate a screen.
 */
export type PropertiesErrorState<TData> =
  | { kind: "loading" }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "validation" }
  | { kind: "error" }
  | { kind: "ok"; data: TData };

/**
 * Map a TanStack Query result to a discriminated UI state (proposal R3). Pure
 * mapper — no React hooks inside — so the name does not start with `use`.
 *
 * Rules, and the two that are decisions rather than convention:
 *
 * - **`401` → `loading`** (R3.4). The auth provider owns the refresh and the
 *   redirect. Reporting an error here would flash a misleading state on every
 *   token rotation, which is a visible flicker for something that is working
 *   as designed.
 * - **`404` → `error`** (R3.5), NOT `not-found`. A collection endpoint does not
 *   "not exist": `GET /api/v1/properties` answers with an empty page when the
 *   tenant has no properties, so a 404 here means something genuinely
 *   unexpected (a proxy rewrite, a wrong base path) and deserves the generic
 *   error with its retry, not a reassuring "nothing found" screen. This is why
 *   `not-found` is unreachable in this feature.
 * - `403` → `forbidden`, a distinct state from the generic error (R3.2).
 * - `422` → `validation`, and the backend's envelope (`message`, `details`,
 *   `code`) is never read, mapped or rendered (R3.3).
 * - `5xx` / network → generic error.
 */
export function mapPropertiesError<TData, TError = Error>(
  queryResult: Pick<
    UseQueryResult<TData, TError>,
    "isPending" | "isError" | "error" | "data"
  >,
): PropertiesErrorState<TData> {
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
      if (error.status === 422) {
        return { kind: "validation" };
      }
      // 404 falls through to the generic error on purpose (R3.5).
    }
    return { kind: "error" };
  }
  return { kind: "ok", data: queryResult.data as TData };
}
