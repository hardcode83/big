import { ApiError } from "@/lib/api";

/**
 * Localized copy for a failure, derived from the `ApiError`'s **status** (design
 * D18). `ApiError.message` is technical and in English by contract
 * (`lib/api/errors.ts`) and is never shown: R1.4 forbids raw error detail.
 *
 * Mapping by status rather than by `error.code` is deliberate — `ErrorCode`
 * values are generic (`CONFLICT`, `VALIDATION_ERROR`) and do not separate the
 * cases a manager needs separated.
 */
const STATUS_KEYS: Record<number, string> = {
  403: "errors.forbidden",
  404: "errors.notFound",
  409: "errors.conflict",
  422: "errors.invalid",
};

export const GENERIC_ERROR_KEY = "errors.generic";

export function errorMessageKey(error: unknown): string {
  if (error instanceof ApiError) {
    return STATUS_KEYS[error.status] ?? GENERIC_ERROR_KEY;
  }
  return GENERIC_ERROR_KEY;
}

/** True for the statuses that have their own dedicated screen (design D17). */
export function isForbidden(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403;
}

export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

export function isConflict(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409;
}

/**
 * True when the backend rejected the write and we can say so: a 4xx is decided
 * before or atomically with the transaction, so nothing was persisted.
 *
 * A 5xx, or anything that is not an `ApiError` at all (a dropped connection), says
 * nothing about whether the row landed — the request may have committed and failed
 * on the way back. Callers that promise the operator "nothing was stored" must ask
 * this first: claiming it over a row that exists is worse than saying nothing,
 * because nobody asks for the deletion of a record they were told does not exist
 * (`steering/security.md` rule 11 exception 4, review 2026-08-21).
 */
export function rejectedWithoutStoring(error: unknown): boolean {
  return (
    error instanceof ApiError && error.status >= 400 && error.status < 500
  );
}
