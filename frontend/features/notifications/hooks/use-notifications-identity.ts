"use client";

import { useAuth } from "@/lib/auth";

/**
 * The tenant and user this session's inbox belongs to, or `null` while there is no session.
 *
 * It returns `null` rather than throwing, which is where this feature parts company with
 * `useIncidents`'s `useTenantId` (design D16). The reason is structural and not caution: in
 * `app/(field)/cleaner/layout.tsx` and `app/(field)/tech/layout.tsx` the `AuthGuard` sits
 * INSIDE the shell (`<CleanerShell><AuthGuard …>{children}</AuthGuard></CleanerShell>`), so
 * the topbar — and the bell in it — renders while the session is still resolving and again
 * while the guard is redirecting. A throw there would take down the whole chrome of both
 * field apps.
 */
export interface NotificationsIdentity {
  tenantId: string;
  userId: string;
}

export function useNotificationsIdentity(): NotificationsIdentity | null {
  const { status, user } = useAuth();
  if (status !== "authenticated" || user === null || user.tenant_id === null) {
    return null;
  }
  return { tenantId: user.tenant_id, userId: user.id };
}
