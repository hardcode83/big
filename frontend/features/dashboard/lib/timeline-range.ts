/**
 * The date-range arithmetic of the timeline filter (design D8). It is isolated
 * here, rather than inlined in the JSX, because it is the one place the screen
 * can earn a `422`:
 *
 * - `<input type="date">` yields a naive `YYYY-MM-DD`, and the domain rejects an
 *   end without a timezone (`backend/app/timeline/domain/repositories.py` raises
 *   `TimelineFilterValidationError` when `tzinfo is None`, mapped to 422 by
 *   `backend/app/timeline/api/errors.py`). Every value returned here carries one.
 * - The range is inclusive at both ends, so `to` is the END of the chosen day.
 *   Sending local midnight as `to` would exclude nearly all of the day the
 *   operator just picked.
 * - The day is taken in the BROWSER's zone, not UTC, because the list formats its
 *   instants in that same zone (`./format.ts` uses `Intl` with no `timeZone`).
 *   Asking for "the 5th" and being shown entries from the 4th would contradict
 *   what the screen itself prints.
 *
 * Anything that is not a real calendar day — `''` from a cleared input above all —
 * is treated as "no end", never as a value. This is a boundary, so it validates
 * here instead of trusting its caller: `Date#toISOString()` throws `RangeError` on
 * an invalid date, which would surface as a crashed render rather than the field
 * error R4.3 requires, and `'' < '2026-08-01'` is lexicographically true, which
 * would make a *cleared* end look like an inverted range.
 */

const DAY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Builds an instant from a `YYYY-MM-DD` day read in the browser's zone, or
 * `undefined` if the string is not a real calendar day.
 */
function localInstant(
  day: string,
  hours: number,
  minutes: number,
  seconds: number,
  milliseconds: number,
): Date | undefined {
  if (!DAY_PATTERN.test(day)) return undefined;
  const [year, month, dayOfMonth] = day.split("-").map(Number);
  const instant = new Date(
    year,
    month - 1,
    dayOfMonth,
    hours,
    minutes,
    seconds,
    milliseconds,
  );
  /*
    The multi-argument `Date` constructor never rejects: month 13 and day 45 roll
    over into the next year, and a year below 100 is remapped into the 1900s
    (`new Date(26, …)` is 1926). Reading the components back is what separates a
    real day from one that merely looks like one.
  */
  if (
    instant.getFullYear() !== year ||
    instant.getMonth() !== month - 1 ||
    instant.getDate() !== dayOfMonth
  ) {
    return undefined;
  }
  return instant;
}

/** True when the string is a real calendar day the helpers below accept. */
function isDay(value?: string): value is string {
  return value !== undefined && localInstant(value, 0, 0, 0, 0) !== undefined;
}

/** Start of the local day, as an instant with a timezone. */
export function startOfDayIso(day: string): string | undefined {
  return localInstant(day, 0, 0, 0, 0)?.toISOString();
}

/** End of the local day, as an instant with a timezone (inclusive `to`). */
export function endOfDayIso(day: string): string | undefined {
  return localInstant(day, 23, 59, 59, 999)?.toISOString();
}

/**
 * True only when both ends are real days and `to` precedes `from`. `YYYY-MM-DD` is
 * fixed-width and zero-padded, so a lexicographic comparison is a chronological
 * one — but only once both sides are known to have that shape, which is why the
 * day check comes first.
 */
export function isInverseRange(fromDate?: string, toDate?: string): boolean {
  return isDay(fromDate) && isDay(toDate) && toDate < fromDate;
}
