"use client";

import { create } from "zustand";

import type {
  ConversationEscalationStatus,
  ConversationStatus,
} from "../data/dto";

/**
 * Lightweight UI state for the inbox (design D6, R2.5): the selected filters and
 * the current page, and nothing else. Conversations and messages are server state
 * owned by TanStack Query and are never stored here.
 *
 * Setting any filter resets the page to 1 — page 3 of one filter does not exist in
 * the next, and asking the backend for it would render an empty list that looks
 * like a failure.
 */
export interface InboxFiltersState {
  status?: ConversationStatus;
  escalationStatus?: ConversationEscalationStatus;
  propertyId?: string;
  page: number;
  setStatus: (value?: ConversationStatus) => void;
  setEscalationStatus: (value?: ConversationEscalationStatus) => void;
  setPropertyId: (value?: string) => void;
  setPage: (page: number) => void;
  reset: () => void;
}

const INITIAL = {
  status: undefined,
  escalationStatus: undefined,
  propertyId: undefined,
  page: 1,
} as const;

export const useInboxFiltersStore = create<InboxFiltersState>((set) => ({
  ...INITIAL,
  setStatus: (status) => set({ status, page: 1 }),
  setEscalationStatus: (escalationStatus) => set({ escalationStatus, page: 1 }),
  setPropertyId: (propertyId) => set({ propertyId, page: 1 }),
  setPage: (page) => set({ page }),
  reset: () => set({ ...INITIAL }),
}));
