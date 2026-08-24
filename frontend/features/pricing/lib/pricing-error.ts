import { ApiError } from "@/lib/api";

/**
 * Maps a failed request to a translated message key (design D9).
 *
 * The choice is made by HTTP **status**, never by `ApiError.message`, `code` or
 * `details`: that message is technical and in English (`lib/api/errors.ts`), and
 * R3.7 forbids painting it. Nothing from the backend's body reaches the screen
 * through here.
 *
 * Three tables rather than one, because the three paths do not share reachable
 * codes — a table listing statuses a path cannot produce is copy nobody will ever
 * see and nobody will ever check:
 *
 *   | path                 | 403 | 404 | 409 | 422 | generic |
 *   |----------------------|-----|-----|-----|-----|---------|
 *   | decide (PATCH)       | yes | yes | yes | yes | yes     |
 *   | regenerate (POST)    | yes |  —  |  —  | yes | yes     |
 *   | read (both listings) | yes |  —  |  —  |  —  | yes     |
 *
 * **No `401` branch**, like `features/cleaning/lib/assign-error.ts`: the HTTP
 * client resolves it with its one-shot refresh and, failing that, with session
 * expiry. Copy of our own here would compete with that redirect.
 */

/**
 * `409` is this screen's own case (R3.6): the recommendation is no longer in the
 * state the row believed, because someone else decided it or the nightly job moved
 * it. It gets copy distinct from the generic error precisely because retrying is
 * not the remedy — reloading is. `mapIncidentsError` could not be reused for this:
 * it has no `409` branch.
 */
const DECIDE_KEY_BY_STATUS: Record<number, string> = {
  403: "pricing:decide.error.forbidden",
  404: "pricing:decide.error.notFound",
  409: "pricing:decide.error.conflict",
  422: "pricing:decide.error.invalid",
};

/**
 * A `property_id` that is unknown, another tenant's, or not `ACTIVE` is a `422`
 * here — the backend treats it as a field of the body naming something the tenant
 * cannot reprice, not as a missing resource. Hence `422` and no `404`.
 */
const GENERATE_KEY_BY_STATUS: Record<number, string> = {
  403: "pricing:generate.error.forbidden",
  422: "pricing:generate.error.invalid",
};

/**
 * Reading distinguishes `403` from the generic error — one string per locale, and
 * it is what a `CLEANER` who reaches `/pricing` from the sidebar sees (design D17).
 * The sidebar does not filter by role, so that arrival is expected rather than
 * exceptional, and «try again in a few seconds» would be false: no amount of
 * retrying grants the permission.
 */
const READ_KEY_BY_STATUS: Record<number, string> = {
  403: "pricing:read.error.forbidden",
};

export const GENERIC_DECIDE_ERROR_KEY = "pricing:decide.error.generic";
export const GENERIC_GENERATE_ERROR_KEY = "pricing:generate.error.generic";
export const GENERIC_READ_ERROR_KEY = "pricing:read.error.generic";

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

export function decideErrorKey(error: unknown): string {
  return keyFor(error, DECIDE_KEY_BY_STATUS, GENERIC_DECIDE_ERROR_KEY);
}

export function generateErrorKey(error: unknown): string {
  return keyFor(error, GENERATE_KEY_BY_STATUS, GENERIC_GENERATE_ERROR_KEY);
}

export function readErrorKey(error: unknown): string {
  return keyFor(error, READ_KEY_BY_STATUS, GENERIC_READ_ERROR_KEY);
}
