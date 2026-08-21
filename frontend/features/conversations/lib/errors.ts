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
