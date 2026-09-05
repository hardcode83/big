import { ApiError } from "@/lib/api";

interface ValidationErrorDetail {
  loc: string[];
  type: string;
  msg: string;
}

/**
 * Map a `422`/`409` `ApiError` into field → message pairs (R3.3, R4.5, design D5).
 *
 * Every other feature's error mapper (`mapConversationsError`, `replyErrorKey`) deliberately
 * never reads the backend's `422` envelope body — R3.3/R4.5 ask for exactly that here ("mostrar
 * el error por campo que la API devuelve, sin inventar un mensaje genérico"), so this is a new
 * pattern for this codebase, not a reuse of an existing one. Both platform forms (design D6)
 * call this one function; it is not duplicated per form.
 *
 * - `422`: reads `error.details.errors` — the shape `_serialisable_validation_errors`
 *   (`backend/app/core/errors.py`) produces: `{loc: string[], type, msg}[]`. Keyed by `loc`'s
 *   last segment (the field name — `loc` is `["body", "<field>"]` for a body validator), value
 *   is `msg`.
 * - `409`: the envelope carries one message with no `loc` at all
 *   (`TenantAlreadyExistsError`, `EmailAlreadyExistsError`) — the field it concerns is
 *   hardcoded per call site via `fallbackField`, because nothing in the response names it.
 *   This is the only branch where a field is inferred rather than read.
 * - Anything else (`403`, `5xx`, network, or a `409` with no `fallbackField`): `{}` — the
 *   caller falls back to the existing generic-error copy pattern (a single localized string).
 */
export function mapFieldErrors(
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

  if (error.status === 409 && fallbackField) {
    return { [fallbackField]: error.message };
  }

  return {};
}
