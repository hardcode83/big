import type { Page } from "@playwright/test";

import { loadRootEnv } from "./load-env";

export type Role = "TENANT_OWNER" | "PROPERTY_MANAGER" | "CLEANER" | "TECHNICIAN";

/**
 * Where each role's real credentials live in the repo root `.env` (see
 * `load-env.ts`). Matches `backend/app/core/config.py` /
 * `backend/app/cli/bootstrap.py` / `backend/app/cli/seed_demo.py` exactly —
 * `TENANT_OWNER`/`PROPERTY_MANAGER` come from `make bootstrap`,
 * `CLEANER`/`TECHNICIAN` from `make seed-demo`.
 */
const ROLE_ENV_VARS: Record<Role, { email: string; password: string }> = {
  TENANT_OWNER: { email: "BOOTSTRAP_OWNER_EMAIL", password: "BOOTSTRAP_OWNER_PASSWORD" },
  PROPERTY_MANAGER: { email: "BOOTSTRAP_MANAGER_EMAIL", password: "BOOTSTRAP_MANAGER_PASSWORD" },
  CLEANER: { email: "SEED_CLEANER_EMAIL", password: "SEED_CLEANER_PASSWORD" },
  TECHNICIAN: { email: "SEED_TECHNICIAN_EMAIL", password: "SEED_TECHNICIAN_PASSWORD" },
};

/**
 * Post-login landing per role (`frontend/features/auth/lib/role-home.ts`).
 * `CLEANER`/`TECHNICIAN` do NOT land here directly — see `loginAs` below.
 */
const ROLE_HOME: Record<Role, string> = {
  TENANT_OWNER: "/dashboard",
  PROPERTY_MANAGER: "/dashboard",
  CLEANER: "/cleaner",
  TECHNICIAN: "/tech",
};

export interface Credentials {
  email: string;
  password: string;
}

export function credentialsFor(role: Role): Credentials {
  loadRootEnv();
  const { email: emailVar, password: passwordVar } = ROLE_ENV_VARS[role];
  const email = process.env[emailVar];
  const password = process.env[passwordVar];
  if (!email || !password) {
    throw new Error(
      `E2E: faltan ${emailVar}/${passwordVar} en el entorno. Son las credenciales reales ` +
        `del rol ${role} (repo root .env, generadas por \`make bootstrap\`/\`make seed-demo\` — ` +
        "steering/security.md #8 no las trae por defecto). Rellena .env o expórtalas en el shell " +
        "que lanza `npm run test:e2e`.",
    );
  }
  return { email, password };
}

/**
 * Logs in by clicking through the real form at `/login` — never bypasses
 * auth (`sdd/steering/frontend.md`: "RBAC del backend decide, el frontend
 * solo oculta"). Selectors verified against
 * `frontend/features/auth/components/login-form.tsx`: `#email`, `#password`,
 * `button[type="submit"]` (no `data-testid`s exist on this form).
 *
 * Lands the actor at their functional shell:
 * - `TENANT_OWNER` / `PROPERTY_MANAGER` → straight to `/dashboard`.
 * - `CLEANER` / `TECHNICIAN` → the login form itself redirects to the
 *   one-tap `/welcome?role=<role>` interstitial first (`role-home.ts` +
 *   `app/(authenticated)/welcome/page.tsx`, D2/R2 of `login-hardening`); this
 *   helper then clicks that page's CTA (an `<a href="/cleaner">` /
 *   `<a href="/tech">`, selected by `href` so it does not depend on the
 *   i18n label) to reach `/cleaner` / `/tech`.
 *
 * (`tasks.md` 1.4 says "esperar /dashboard" for all roles; that only holds
 * for the two manager-side roles — see the `/welcome` detour above. Noted in
 * Implementation Notes for the section 2-4 implementers.)
 */
export async function loginAs(page: Page, role: Role): Promise<void> {
  const { email, password } = credentialsFor(role);
  const home = ROLE_HOME[role];

  await page.goto("/login");
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  await page.locator('button[type="submit"]').click();

  if (role === "CLEANER" || role === "TECHNICIAN") {
    await page.waitForURL(/\/welcome(\?|$)/);
    await page.locator(`a[href="${home}"]`).click();
  }

  await page.waitForURL((url) => url.pathname === home);
}
