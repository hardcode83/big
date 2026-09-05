/**
 * Two decimals with an optional leading digit; accepts both `0.50` and
 * `.50` and rejects commas, exponents and trailing punctuation. The backend
 * schema accepts `number | string` (openapi.d.ts:3284), so the validated
 * value travels to the wire as a string to keep the formatting verbatim.
 *
 * Extracted from `resolve-incident-dialog.tsx` (design D11): this is the
 * same client-side gate used for the resolve dialog's `final_cost` and for
 * the manager's triage `estimated_cost` (R3.2) — one expression, one home.
 */
const POSITIVE_DECIMAL = /^\d+(\.\d{1,2})?$|^\.\d{1,2}$/;

export function isPositiveDecimal(value: string): boolean {
  return POSITIVE_DECIMAL.test(value);
}
