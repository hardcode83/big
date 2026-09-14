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
