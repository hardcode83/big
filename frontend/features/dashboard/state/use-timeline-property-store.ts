"use client";

import { create } from "zustand";

/**
 * The property chosen on `/timeline`, held **in memory only** (R1.4): a
 * `property_id` identifies a tenant's asset and browser storage is not scoped by
 * tenant, so it never reaches `localStorage`, `sessionStorage` or a cookie.
 *
 * It stores the PAIR `{ tenantId, propertyId }` rather than a bare id because
 * `logout` clears tokens and the user but not the Zustand stores
 * (`lib/auth/auth-provider.tsx`). A bare id would survive a logout → login as a
 * different tenant in the same tab and fire a read against a foreign property,
 * which the backend answers with a 404 indistinguishable from "does not exist"
 * and the retry policy does not retry — a mute failure. The consumer honours the
 * selection only when the tenant matches (design D3).
 */
export interface TimelinePropertyState {
  tenantId?: string;
  propertyId?: string;
  select: (tenantId: string, propertyId: string) => void;
  clear: () => void;
}

export const useTimelinePropertyStore = create<TimelinePropertyState>((set) => ({
  tenantId: undefined,
  propertyId: undefined,
  select: (tenantId, propertyId) => set({ tenantId, propertyId }),
  clear: () => set({ tenantId: undefined, propertyId: undefined }),
}));

/**
 * The selection, but only for the tenant that owns it — the read every consumer
 * should use.
 *
 * The comparison lives here, next to the state that carries the risk, rather than
 * only in the consumer: reading the bare `propertyId` is precisely the mistake
 * D3 exists to prevent, so the safe read is the ergonomic one and forgetting the
 * check takes deliberate effort. Raised by the security panel on sections 3-4
 * (security.md rule 1: a new module carries its own isolation test).
 */
export function useSelectedTimelineProperty(
  tenantId: string,
): string | undefined {
  return useTimelinePropertyStore((state) =>
    state.tenantId === tenantId ? state.propertyId : undefined,
  );
}
