"use client";

import { create } from "zustand";

import type { CleaningTaskStatus } from "../data";

/**
 * Lightweight UI state for the cleaning list's filters and page
 * (`steering/frontend.md`: Zustand is for UI state only). It holds ONLY the
 * selected values — never the tasks themselves, which are server state owned by
 * TanStack Query.
 *
 * **The reset to page 1 lives inside the setters** (design D6): R3.4 is an
 * invariant of the store, not a courtesy each caller has to remember, so a
 * filter change can never leave a page offset inherited from the previous filter
 * and show an empty page nobody asked for.
 *
 * For the same reason the store also records **which tenant its filters belong to**.
 * Being a module-level singleton it outlives the view and outlives the session: a
 * `propertyId` chosen by one session would otherwise be re-sent on the next
 * session's first request, carrying one tenant's opaque identifier into another's
 * (`steering/security.md` rule 1, frontend side). A component-scoped ref cannot
 * catch that, because logging out unmounts the view — so the ownership has to live
 * exactly where the filters live.
 */
export interface CleaningFiltersState {
  /** The tenant these filters were chosen in; `undefined` until one adopts them. */
  tenantId?: string;
  propertyId?: string;
  status?: CleaningTaskStatus;
  page: number;
  /** Records the current tenant, discarding filters chosen in a different one. */
  adoptTenant: (tenantId?: string) => void;
  setPropertyId: (value?: string) => void;
  setStatus: (value?: CleaningTaskStatus) => void;
  setPage: (page: number) => void;
  clearPropertyId: () => void;
  clearStatus: () => void;
  reset: () => void;
}

// `tenantId` belongs in here so `reset()` really returns to the initial state: a
// store that kept its recorded tenant across a reset would claim filters it no
// longer holds, and would make any test that resets order-dependent.
const INITIAL = {
  tenantId: undefined,
  propertyId: undefined,
  status: undefined,
  page: 1,
} as const;

export const useCleaningFiltersStore = create<CleaningFiltersState>((set) => ({
  ...INITIAL,
  adoptTenant: (tenantId) =>
    set((current) =>
      current.tenantId === tenantId ? current : { ...INITIAL, tenantId },
    ),
  setPropertyId: (propertyId) => set({ propertyId, page: 1 }),
  setStatus: (status) => set({ status, page: 1 }),
  setPage: (page) => set({ page }),
  clearPropertyId: () => set({ propertyId: undefined, page: 1 }),
  clearStatus: () => set({ status: undefined, page: 1 }),
  reset: () => set({ ...INITIAL }),
}));
