import type { UserRole } from "../data/dto";

/**
 * Who may operate the inbox (design D12). Exhaustive over the generated
 * `UserRole` literal, so a new role must be decided here rather than defaulting.
 *
 * This is **UX, not authorization** (R6.2): the backend decides
 * (`app/auth/domain/policy.py` gives `MANAGE_CONVERSATIONS` to
 * `PROPERTY_MANAGER` alone), and a 403 on an action the UI offered is handled
 * like any other error. Hiding a control never stands in for a permission check.
 */
const MANAGE_CONVERSATIONS: Record<UserRole, boolean> = {
  SUPER_ADMIN: false,
  TENANT_OWNER: false,
  PROPERTY_MANAGER: true,
  CLEANER: false,
  TECHNICIAN: false,
};

export function canManageConversations(role: UserRole): boolean {
  return MANAGE_CONVERSATIONS[role];
}
