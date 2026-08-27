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
 *
 * Role-to-permission grants **must mirror `backend/app/auth/domain/policy.py`**:
 * - `messaging-ai` D17 says reading conversations is the owner's and the
 *   manager's, but **operating** the inbox is the manager's alone. The owner
 *   reads but does not write. Granting `MANAGE_CONVERSATIONS` to `TENANT_OWNER`
 *   here would surface a composer that the backend immediately refuses with
 *   403 on every submission — a defect that the automated suite cannot catch
 *   because it mocks this hook instead of round-tripping through the policy.
 *   This rule is the source of truth; this map is a UX hint of it.
 */
type UserRole = components["schemas"]["UserRole"];

export type Permission =
  | "MANAGE_CLEANING_TASKS"
  | "MANAGE_CONVERSATIONS"
  | "MANAGE_PRICE_RECOMMENDATIONS";

export const ROLE_UI_PERMISSIONS: Record<UserRole, readonly Permission[]> = {
  SUPER_ADMIN: [],
  // `MANAGE_PRICE_RECOMMENDATIONS` goes to the owner too, and that is not a
  // copy-paste slip of the line above (R7.1, R7.2). `policy.py:128-142`
  // documents it as a conscious divergence from «the owner sees, the manager
  // operates»: `min_price`/`max_price` are the limits of the owner's own money,
  // and PRD §19 Mode 1 says «Manager/owner aprueba manualmente». Giving this
  // the shape of `MANAGE_CLEANING_TASKS` would leave the owner staring at a
  // queue she cannot decide, with the buttons hidden by the frontend while the
  // backend was granting them.
  // `MANAGE_CONVERSATIONS` is the other side of that rule (messaging-ai D17):
  // the owner reads but does not write, so she is intentionally absent here.
  TENANT_OWNER: ["MANAGE_PRICE_RECOMMENDATIONS"],
  PROPERTY_MANAGER: [
    "MANAGE_CLEANING_TASKS",
    "MANAGE_CONVERSATIONS",
    "MANAGE_PRICE_RECOMMENDATIONS",
  ],
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
