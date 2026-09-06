/**
 * Maps the role returned by `/api/v1/auth/me` to the shell route the user
 * should land on after a successful login when no `?returnTo=` is present.
 *
 * Five entries: the four MVP tenant-scoped roles, plus `SUPER_ADMIN` (added by
 * `super-admin-console` R1.1/R1.2) — a role with no tenant of its own, so it
 * never falls into the `/dashboard` default the way an unlisted role would. A
 * role outside this table still lands on `/dashboard` until it gets its own
 * row — that is the behaviour the proposal's R4 promises and what the
 * table-driven helper gives for free. Exported as a `const` so tests can
 * enumerate the mapping without duplicating the values here.
 *
 * Lives in `features/auth/lib/` because the only caller today is the
 * `LoginForm`; a future role-aware redirect elsewhere belongs here too.
 */
export const ROLE_HOME: Record<string, string> = {
  TENANT_OWNER: "/dashboard",
  PROPERTY_MANAGER: "/dashboard",
  CLEANER: "/cleaner",
  TECHNICIAN: "/tech",
  SUPER_ADMIN: "/platform",
};

export function roleHome(role: string | undefined): string {
  return (role && ROLE_HOME[role]) || "/dashboard";
}