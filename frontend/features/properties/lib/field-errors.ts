import { ApiError } from "@/lib/api";

interface ValidationErrorDetail {
  loc: string[];
  type: string;
  msg: string;
}

/**
 * Map a `422`/`409` `ApiError` into field → message pairs for the property
 * create/edit forms (R1.5, R2.7, design D6). Sibling to
 * `features/properties/lib/error-mapping.ts` (untouched — that module maps
 * query results, not mutation errors) and to
 * `features/platform/lib/field-errors.ts` (whose `422` branch this mirrors
 * exactly).
 *
 * - `422`: reads `error.details.errors` — the shape
 *   `_serialisable_validation_errors` (`backend/app/core/errors.py`)
 *   produces: `{loc: string[], type, msg}[]`. Keyed by `loc`'s last segment.
 * - `409`: unlike platform's single-field conflict, this endpoint has two
 *   possible conflicting columns and neither duplicate-key error carries a
 *   `loc` (`backend/app/properties/infrastructure/repositories.py:551-558`
 *   raises both with a plain string and no `details`, design D6) — so the
 *   field is inferred by matching the exact substring `"internal_code"` or
 *   `"pms_external_id"` in `error.message`. `fallbackField`, when given, is
 *   used only if the message matches neither substring.
 * - Anything else (`403`, `5xx`, network, unmatched `409` with no
 *   `fallbackField`): `{}` — the caller falls back to a generic error.
 */
export function mapPropertyFieldErrors(
  error: unknown,
  fallbackField?: string,
): Record<string, string> {
  if (!(error instanceof ApiError)) {
    return {};
  }

  if (error.status === 422) {
    const details = error.details as { errors?: unknown } | undefined;
    const errors = details?.errors;
    if (!Array.isArray(errors)) {
      return {};
    }
    const result: Record<string, string> = {};
    for (const item of errors as ValidationErrorDetail[]) {
      const field = item.loc?.[item.loc.length - 1];
      if (field) {
        result[field] = item.msg;
      }
    }
    return result;
  }

  if (error.status === 409) {
    if (error.message.includes("internal_code")) {
      return { internal_code: error.message };
    }
    if (error.message.includes("pms_external_id")) {
      return { pms_external_id: error.message };
    }
    if (fallbackField) {
      return { [fallbackField]: error.message };
    }
  }

  return {};
}
