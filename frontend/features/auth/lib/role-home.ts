/**
 * Maps the role returned by `/api/v1/auth/me` to the shell route the user
 * should land on after a successful login when no `?returnTo=` is present.
 *
 * The four entries cover the MVP roles. A new role lands on `/dashboard` until
 * it gets its own row — that is the behaviour the proposal's R4 promises and
 * what the table-driven helper gives for free. Exported as a `const` so tests
 * can enumerate the mapping without duplicating the values here.
 *
 * Lives in `features/auth/lib/` because the only caller today is the
 * `LoginForm`; a future role-aware redirect elsewhere belongs here too.
 */
export const ROLE_HOME: Record<string, string> = {
  TENANT_OWNER: "/dashboard",
  PROPERTY_MANAGER: "/dashboard",
  CLEANER: "/cleaner",
  TECHNICIAN: "/tech",
};

export function roleHome(role: string | undefined): string {
  return (role && ROLE_HOME[role]) || "/dashboard";
}