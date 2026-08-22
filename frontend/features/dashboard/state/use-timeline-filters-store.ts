"use client";

import { create } from "zustand";

import type { TimelineActorType, TimelineSeverity } from "../data";
import { endOfDayIso, isInverseRange, startOfDayIso } from "../lib/timeline-range";

/**
 * Lightweight UI state for the property timeline filters (frontend.md: Zustand is
 * for UI state only). It holds ONLY the selected filter values — never the
 * timeline entries themselves, which are server state owned by TanStack Query.
 *
 * The date range is kept twice on purpose (design D8): `fromDate`/`toDate` are the
 * DRAFT the two date inputs show, in the `YYYY-MM-DD` they emit, while `from`/`to`
 * are the COMMITTED instants the query actually sends. They diverge exactly while
 * the draft is inverse, which is what lets the screen show a field error without
 * the query key moving.
 */
export interface TimelineFiltersState {
  actorType?: TimelineActorType;
  severity?: TimelineSeverity;
  /** Timeline event type (PRD §10 "por tipo de evento"); open enum, kept as string. */
  eventType?: string;
  /** Draft range ends, `YYYY-MM-DD` as the date input produces them. */
  fromDate?: string;
  toDate?: string;
  /** Committed range ends — instants with a timezone, only ever a valid draft. */
  from?: string;
  to?: string;
  page: number;
  setActorType: (value?: TimelineActorType) => void;
  setSeverity: (value?: TimelineSeverity) => void;
  setEventType: (value?: string) => void;
  setRange: (fromDate?: string, toDate?: string) => void;
  setPage: (page: number) => void;
  reset: () => void;
}

const EMPTY = {
  actorType: undefined,
  severity: undefined,
  eventType: undefined,
  fromDate: undefined,
  toDate: undefined,
  from: undefined,
  to: undefined,
  page: 1,
} as const;

/**
 * Every filter setter writes `page: 1` in the **same** mutation (design D7).
 * Doing it in a `useEffect` instead would race: changing a filter while on page 3
 * would first query page 3 of the new filter and only then fall back to page 1.
 * The invariant belongs to the transition, so it lives where the transition is.
 *
 * `setRange` follows the same rule for the same reason, with one refinement D7 and
 * D8 leave implicit: while the draft is inverse it resets NOTHING. The committed
 * pair is left exactly as it was AND so is the page, because the query key must
 * not move at all — not for the request the server would answer with a 422, and
 * not for the collateral "valid" one a page reset would produce (design D8).
 */
export const useTimelineFiltersStore = create<TimelineFiltersState>((set) => ({
  ...EMPTY,
  setActorType: (actorType) => set({ actorType, page: 1 }),
  setSeverity: (severity) => set({ severity, page: 1 }),
  setEventType: (eventType) => set({ eventType, page: 1 }),
  setRange: (fromDate, toDate) =>
    set(
      isInverseRange(fromDate, toDate)
        ? // Draft only: neither the committed pair NOR the page moves. The page
          // reset exists because the result set changed, and here it did not —
          // moving it would change the query key and fire the "collateral valid"
          // request D8 forbids, silently jumping the reader back to page 1 while
          // the field error is on screen. Found by the browser check in
          // `/sdd:run`, which caught what the unit test missed by already being
          // on page 1.
          { fromDate, toDate }
        : {
            fromDate,
            toDate,
            from: fromDate ? startOfDayIso(fromDate) : undefined,
            to: toDate ? endOfDayIso(toDate) : undefined,
            page: 1,
          },
    ),
  setPage: (page) => set({ page }),
  reset: () => set({ ...EMPTY }),
}));
