/**
 * "Waiting since" relative-time bucket for a pending approval row (R2.1, R2.6).
 *
 * Presentational only — no business logic. Given the backend's ISO-8601
 * `requestedAt` timestamp, returns the unit (`minutes`/`hours`/`days`) and the
 * count the component interpolates into `approvals:queue.waitingSince.<unit>`,
 * whose locale entries carry the `_one`/`_other` i18next pluralization forms.
 *
 * Mirrors `features/dashboard/lib/format.ts`'s `parseTimestamp` convention: an
 * unparseable timestamp returns `null` rather than throwing or silently
 * defaulting to "0 minutes", so the caller can fall back to painting nothing
 * misleading.
 */
export interface WaitingSince {
  unit: "minutes" | "hours" | "days";
  count: number;
}

const MINUTE_MS = 60 * 1000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

export function waitingSince(
  requestedAt: string,
  now: Date = new Date(),
): WaitingSince | null {
  if (typeof requestedAt !== "string" || requestedAt.trim() === "") {
    return null;
  }
  const requested = new Date(requestedAt);
  if (Number.isNaN(requested.getTime())) {
    return null;
  }
  const elapsedMs = Math.max(0, now.getTime() - requested.getTime());
  if (elapsedMs < HOUR_MS) {
    return { unit: "minutes", count: Math.max(1, Math.floor(elapsedMs / MINUTE_MS)) };
  }
  if (elapsedMs < DAY_MS) {
    return { unit: "hours", count: Math.floor(elapsedMs / HOUR_MS) };
  }
  return { unit: "days", count: Math.floor(elapsedMs / DAY_MS) };
}
