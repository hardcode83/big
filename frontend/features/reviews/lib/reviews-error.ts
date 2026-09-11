import { ApiError } from "@/lib/api";

/**
 * Maps a failed request to a translated message key (design D10).
 *
 * The choice is made by HTTP **status**, never by `ApiError.message`, `code` or
 * `details`: that message is technical and in English (`lib/api/errors.ts`), and
 * R3.6/R3.7 forbid painting it. Nothing from the backend's body reaches the
 * screen through here.
 *
 * Three tables rather than one, because the three paths do not share reachable
 * codes — a table listing statuses a path cannot produce is copy nobody will ever
 * see and nobody will ever check:
 *
 *   | path                          | 403 | 404 | 409 | 422 | generic |
 *   |-------------------------------|-----|-----|-----|-----|---------|
 *   | respond / edit (PATCH)        | yes | yes | yes | yes | yes     |
 *   | create (POST)                 | yes |  —  |  —  | yes | yes     |
 *   | read (listings + detail/draft)| yes | yes |  —  |  —  | yes     |
 *
 * **No `401` branch**: the HTTP client resolves it with its one-shot refresh
 * and, failing that, with session expiry. Copy of our own here would compete
 * with that redirect.
 */

/**
 * `409` is this screen's own case (R3.5): the review is no longer in the state
 * the row believed, because someone else decided it or the AI pipeline moved
 * it. It gets copy distinct from the generic error precisely because retrying
 * is not the remedy — reloading is.
 */
const RESPOND_KEY_BY_STATUS: Record<number, string> = {
  403: "reviews:respond.error.forbidden",
  404: "reviews:respond.error.notFound",
  409: "reviews:respond.error.conflict",
  422: "reviews:respond.error.invalid",
};

/**
 * A `property_id` that is unknown, another tenant's, or otherwise invalid is
 * a `422` here — the backend treats it as a field of the body naming something
 * the tenant cannot create. Hence `422` and no `404`.
 */
const CREATE_KEY_BY_STATUS: Record<number, string> = {
  403: "reviews:create.error.forbidden",
  422: "reviews:create.error.invalid",
};

/**
 * Reading distinguishes `403` and `404` from the generic error — both can occur
 * (the `404` for a stale detail/draft lookup, the `403` for a forbidden role).
 * `CLEANER`/`TECHNICIAN` arriving via the sidebar get the `403` copy because
 * the sidebar does not filter by role.
 */
const READ_KEY_BY_STATUS: Record<number, string> = {
  403: "reviews:read.error.forbidden",
  404: "reviews:read.error.notFound",
};

export const GENERIC_RESPOND_ERROR_KEY = "reviews:respond.error.generic";
export const GENERIC_CREATE_ERROR_KEY = "reviews:create.error.generic";
export const GENERIC_READ_ERROR_KEY = "reviews:read.error.generic";

function keyFor(
  error: unknown,
  table: Record<number, string>,
  generic: string,
): string {
  if (!(error instanceof ApiError)) {
    return generic;
  }
  return table[error.status] ?? generic;
}

export function respondErrorKey(error: unknown): string {
  return keyFor(error, RESPOND_KEY_BY_STATUS, GENERIC_RESPOND_ERROR_KEY);
}

export function createErrorKey(error: unknown): string {
  return keyFor(error, CREATE_KEY_BY_STATUS, GENERIC_CREATE_ERROR_KEY);
}

export function readErrorKey(error: unknown): string {
  return keyFor(error, READ_KEY_BY_STATUS, GENERIC_READ_ERROR_KEY);
}