"use client";

import { useAuth } from "./auth-provider";
import type { components } from "@/lib/api/generated/openapi";

/**
 * UX hint only — the backend is the authority (`steering/frontend.md`: "RBAC del
 * backend decide, el frontend solo oculta"; `steering/security.md` rule 2). A
 * hidden control is a convenience, never a guarantee: an action this map would
 * have allowed can still be refused with a `403`, and that refusal is never read
 * as success.
 *
 * The map is deliberately **partial** (design D7): it declares only the
 * permissions the frontend uses to hide something. A mirror that claimed to be
 * complete would go stale in silence the moment the backend adds a permission;
 * one that says what it covers only ever lies about what it enumerates.
 */
type UserRole = components["schemas"]["UserRole"];

export type Permission = "MANAGE_CLEANING_TASKS";

export const ROLE_UI_PERMISSIONS: Record<UserRole, readonly Permission[]> = {
  SUPER_ADMIN: [],
  TENANT_OWNER: [],
  PROPERTY_MANAGER: ["MANAGE_CLEANING_TASKS"],
  CLEANER: [],
  TECHNICIAN: [],
};

/** False without an authenticated user: nothing is unlocked by absence of a role. */
export function useHasPermission(permission: Permission): boolean {
  const { user } = useAuth();
  if (!user) {
    return false;
  }
  // `?? []` for the same reason `components/property-state-badge.tsx` falls back
  // to grey: `role` crosses the API boundary, and a role the generated union does
  // not know must hide the control, not crash the view.
  return (ROLE_UI_PERMISSIONS[user.role] ?? []).includes(permission);
}
