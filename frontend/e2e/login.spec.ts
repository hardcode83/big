import { expect, test } from "@playwright/test";

import { credentialsFor, loginAs } from "./fixtures/auth";
import { resolveBackendUrl } from "./fixtures/load-env";
import { apiLogin, createUserWithTemporaryPassword } from "./fixtures/seed-context";

// Derived from `BACKEND_HEALTH_URL` when `BACKEND_URL` isn't set explicitly —
// see `fixtures/load-env.ts` `resolveBackendUrl` — so the worktree command in
// task 7.3 only needs to export the one (already-required) health var.
const BACKEND_URL = resolveBackendUrl();

/**
 * R2 — the one critical E2E flow steering/testing.md names by name: login.
 *
 * Uses `PROPERTY_MANAGER` throughout (not `TENANT_OWNER`/`CLEANER`/`TECHNICIAN`)
 * because it lands straight on `/dashboard` (see `fixtures/auth.ts` `loginAs`'s
 * `ROLE_HOME` — `CLEANER`/`TECHNICIAN` detour through `/welcome` first) and
 * because `POST /api/v1/users` (used below for the `must_change_password`
 * case) requires `MANAGE_USERS`, which `PROPERTY_MANAGER` holds.
 */
test.describe("login", () => {
  test("valid credentials redirect to the role's landing page", async ({ page }) => {
    await loginAs(page, "PROPERTY_MANAGER");
    await expect(page).toHaveURL(/\/dashboard/);
  });

  test("invalid credentials show an error and do not redirect", async ({ page }) => {
    // R2.2 + steering/security.md #7: the rate limiter allows 10/min/IP before
    // lockout, so one deliberate bad attempt is enough to prove the error path
    // without spending the budget a retry loop would.
    const { email } = credentialsFor("PROPERTY_MANAGER");

    await page.goto("/login");
    await page.locator("#email").fill(email);
    await page.locator("#password").fill("definitely-the-wrong-password");
    await page.locator('button[type="submit"]').click();

    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page).toHaveURL(/\/login/);
  });

  test("must_change_password blocks authenticated routes except me/logout/change-password", async ({
    request,
  }) => {
    // R2.3 + docs/auth-account-recovery.md ("El gate PASSWORD_CHANGE_REQUIRED"):
    // create a fresh user via the admin API instead of resetting a seeded one —
    // `CreateUserUseCase` always sets `must_change_password: true`, so this is
    // the cheapest realistic way to get one without touching the CLEANER/
    // TECHNICIAN credentials sections 3/4 rely on. `MANAGE_USERS` is
    // `TENANT_OWNER`-only (`backend/app/auth/domain/policy.py` `_USER_MANAGE` is
    // folded into `ROLE_PERMISSIONS[TENANT_OWNER]` but not `PROPERTY_MANAGER`'s) —
    // confirmed by a live 403 FORBIDDEN when this was first tried with the manager.
    const ownerCreds = credentialsFor("TENANT_OWNER");
    const ownerSession = await apiLogin(ownerCreds.email, ownerCreds.password);
    const { email, temporaryPassword } = await createUserWithTemporaryPassword(
      ownerSession,
      "PROPERTY_MANAGER",
    );

    // The gate lets login and refresh through (docs/auth-account-recovery.md:
    // "puede hacer login y obtener el par de tokens").
    const loginResponse = await request.post(`${BACKEND_URL}/api/v1/auth/login`, {
      data: { email, password: temporaryPassword },
    });
    expect(loginResponse.status()).toBe(200);
    const { access_token: accessToken } = (await loginResponse.json()) as {
      access_token: string;
    };
    const authHeader = { Authorization: `Bearer ${accessToken}` };

    // Representative non-exempt authenticated request: blocked.
    const propertiesResponse = await request.get(`${BACKEND_URL}/api/v1/properties`, {
      headers: authHeader,
    });
    expect(propertiesResponse.status()).toBe(403);
    const propertiesBody = (await propertiesResponse.json()) as {
      error?: { code?: string };
      code?: string;
    };
    expect(propertiesBody.error?.code ?? propertiesBody.code).toBe(
      "PASSWORD_CHANGE_REQUIRED",
    );

    // The three exemptions: me, logout, change-password — all pass despite the flag.
    const meResponse = await request.get(`${BACKEND_URL}/api/v1/auth/me`, {
      headers: authHeader,
    });
    expect(meResponse.status()).toBe(200);
    const meBody = (await meResponse.json()) as { must_change_password: boolean };
    expect(meBody.must_change_password).toBe(true);

    const changePasswordResponse = await request.post(
      `${BACKEND_URL}/api/v1/auth/change-password`,
      {
        headers: authHeader,
        data: {
          current_password: temporaryPassword,
          new_password: "a-brand-new-e2e-password-123",
        },
      },
    );
    expect(changePasswordResponse.status()).toBe(204);

    // `change-password` revokes every refresh family, including the one that made
    // the call (docs/auth-account-recovery.md) — so a fresh login is needed for
    // `logout`, and the flag is now cleared.
    const secondLoginResponse = await request.post(`${BACKEND_URL}/api/v1/auth/login`, {
      data: { email, password: "a-brand-new-e2e-password-123" },
    });
    expect(secondLoginResponse.status()).toBe(200);
    const { access_token: secondAccessToken } = (await secondLoginResponse.json()) as {
      access_token: string;
    };

    const logoutResponse = await request.post(`${BACKEND_URL}/api/v1/auth/logout`, {
      headers: { Authorization: `Bearer ${secondAccessToken}` },
    });
    expect(logoutResponse.status()).toBe(204);
  });
});
