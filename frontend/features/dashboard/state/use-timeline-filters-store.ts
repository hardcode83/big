"use client";

import { create } from "zustand";

import type { TimelineActorType, TimelineSeverity } from "../data";

/**
 * Lightweight UI state for the property timeline filters (frontend.md: Zustand is
 * for UI state only). It holds ONLY the selected filter values — never the
 * timeline entries themselves, which are server state owned by TanStack Query.
 */
export interface TimelineFiltersState {
  actorType?: TimelineActorType;
  severity?: TimelineSeverity;
  /** Timeline event type (PRD §10 "por tipo de evento"); open enum, kept as string. */
  eventType?: string;
  setActorType: (value?: TimelineActorType) => void;
  setSeverity: (value?: TimelineSeverity) => void;
  setEventType: (value?: string) => void;
  reset: () => void;
}

export const useTimelineFiltersStore = create<TimelineFiltersState>((set) => ({
  actorType: undefined,
  severity: undefined,
  eventType: undefined,
  setActorType: (actorType) => set({ actorType }),
  setSeverity: (severity) => set({ severity }),
  setEventType: (eventType) => set({ eventType }),
  reset: () =>
    set({ actorType: undefined, severity: undefined, eventType: undefined }),
}));
