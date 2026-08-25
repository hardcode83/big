/**
 * Non-sensitive presence flag for the marketing redirect on `/`.
 *
 * The cookie value is the literal `"1"` and only signals that the JS runtime
 * held a session at some point — it carries no token, no user id, no PII, and
 * no expiration beyond the browser session. It exists so the server can decide
 * whether to redirect `/` to `/dashboard` (R1.2) without forcing a token onto
 * disk: the JS session store stays in memory, this cookie only mirrors its
 * existence for the server-side read.
 *
 * Mirrors the posture of `THEME_COOKIE`/`LOCALE_COOKIE` (same
 * `path=/`/`samesite=lax`, same `no secure` in dev for localhost).
 */
import { SESSION_PRESENT_COOKIE } from "@/lib/config/constants";

export { SESSION_PRESENT_COOKIE };

const COOKIE_VALUE = "1";
const COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365; // 1 year; capped by browser session

function writeCookie(name: string, value: string, maxAgeSeconds: number): void {
  document.cookie = `${name}=${value}; path=/; max-age=${maxAgeSeconds}; samesite=lax`;
}

function clearCookie(name: string): void {
  document.cookie = `${name}=; path=/; max-age=0; samesite=lax`;
}

export function markSessionPresent(): void {
  writeCookie(SESSION_PRESENT_COOKIE, COOKIE_VALUE, COOKIE_MAX_AGE_SECONDS);
}

export function clearSessionPresent(): void {
  clearCookie(SESSION_PRESENT_COOKIE);
}
