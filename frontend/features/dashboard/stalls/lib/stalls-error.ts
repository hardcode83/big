import { ApiError } from "@/lib/api";

/**
 * Maps a failed blocked-transition mutation to a translated message key
 * (proposal `blocked-transitions-web` R3.3, R3.4).
 *
 * Same shape as `features/cleaning/lib/assign-error.ts` and
 * `features/pricing/lib/pricing-error.ts`, and for the same reason: the choice
 * is made by HTTP **status**, never by `ApiError.message` — that message is
 * technical and in English (`lib/api/errors.ts`), so painting it would leak
 * backend detail into an operator's screen.
 *
 * Two statuses earn their own copy; everything else falls back to the caller's
 * generic key, which names the action ("no se pudo cancelar la limpieza")
 * rather than the blocker:
 *
 *   403 — the caller lost the permission between render and click. R2.4 makes
 *         this unreachable through the UI (the button is not painted without
 *         the permission), but a role revoked mid-session reaches it, and
 *         «vuelve a intentarlo» would be false: no amount of retrying grants
 *         a permission.
 *   409 — the stall is no longer in the state the row believed, which is the
 *         case R3.4 names explicitly: the backend refuses the cancellation
 *         because a guest is already in the property, or because another
 *         person resolved it first. Retrying is not the remedy — re-reading
 *         is, and `onSettled` already invalidated the bucket.
 *
 * **No `401` branch**, like both precedents: the HTTP client resolves it with
 * its one-shot refresh (`lib/api/client.ts:207-224`) and, failing that, with
 * session expiry. Copy of our own here would compete with that redirect.
 */
const KEY_BY_STATUS: Record<number, string> = {
  403: "card.blocked.error.forbidden",
  409: "card.blocked.error.conflict",
};

/**
 * Resolves the message key for a failed mutation.
 *
 * `genericKey` is the per-action fallback the dialog owns
 * (`card.blocked.cancelCleaning.dialog.error.generic` or its resolve-incident
 * twin), so an unmapped status still names which action failed.
 */
export function stallsErrorKey(error: unknown, genericKey: string): string {
  if (!(error instanceof ApiError)) {
    return genericKey;
  }
  return KEY_BY_STATUS[error.status] ?? genericKey;
}
