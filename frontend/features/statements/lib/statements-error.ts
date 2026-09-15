import type { UseQueryResult } from "@tanstack/react-query";

import { ApiError } from "@/lib/api";

/**
 * Maps a failed `GET /api/v1/owner-statements` (or detail) request to a
 * translated message key (R1.2, task 3.4).
 *
 * The choice is made by HTTP **status**, never by `ApiError.message`, `code`
 * or `details` — that message is technical and in English, and R5.4 forbids
 * painting raw backend text. Same discipline as
 * `features/reviews/lib/reviews-error.ts:readErrorKey` and
 * `features/pricing/lib/pricing-error.ts:readErrorKey`.
 *
 * **No `401` branch**: the shared HTTP client (`ApiClient`) resolves a `401`
 * with its own one-shot refresh and, failing that, session expiry — a
 * redirect this feature must not compete with. Only `403` (authenticated but
 * not entitled to owner-statements reads) gets a distinct, non-generic
 * message here; both `403` and any other failure render through the same
 * `ErrorState`, so no financial data is ever shown for either (R1.2).
 */
const READ_KEY_BY_STATUS: Record<number, string> = {
  403: "statements:read.error.forbidden",
};

export const GENERIC_READ_ERROR_KEY = "statements:read.error.generic";

export function readErrorKey(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return GENERIC_READ_ERROR_KEY;
  }
  return READ_KEY_BY_STATUS[error.status] ?? GENERIC_READ_ERROR_KEY;
}

/**
 * A discriminated union of the UI states `StatementDetailState` (task 4.4)
 * needs to render for `GET /owner-statements/{id}`. Pure mapper — no React
 * hooks — same shape/discipline as
 * `features/reservations/lib/error-mapping.ts:mapReservationsError`.
 *
 * Rules (R1.2, R3.7):
 * - `isPending`: `loading`.
 * - `401`: delegated to the shared session-refresh/expiry flow (the same
 *   discipline `readErrorKey` documents for the list) — stays `loading` so
 *   this component never flashes a misleading `error`/`not-found` for what
 *   is actually a session expiry.
 * - `403`: `forbidden` — authenticated but not entitled; no financial data
 *   is ever attached to this variant.
 * - `404`: `not-found`. Per the backend contract (R3.7 / R7.2 del backend),
 *   this status means EITHER "no such id" OR "id belongs to another
 *   tenant" — this mapper deliberately collapses both into the same
 *   variant with no extra detail, so the component cannot leak which one
 *   occurred even by accident.
 * - anything else (`422`, `5xx`, network/`TypeError`): generic `error`.
 * - success: `ok` with the data.
 */
export type StatementDetailState<TData> =
  | { kind: "loading" }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" }
  | { kind: "ok"; data: TData };

export function mapStatementDetailState<TData>(
  queryResult: Pick<UseQueryResult<TData>, "isPending" | "isError" | "error" | "data">,
): StatementDetailState<TData> {
  if (queryResult.isPending) {
    return { kind: "loading" };
  }
  if (queryResult.isError) {
    const error = queryResult.error;
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
    }
    return { kind: "error" };
  }
  return { kind: "ok", data: queryResult.data as TData };
}
