import { defineConfig, devices } from "@playwright/test";

/**
 * Separate project from Vitest (design D1): specs live in `frontend/e2e/`,
 * run against the real `make up` stack (frontend + backend + postgres +
 * redis + worker + beat), never inside `vitest.config.ts`. Run with
 * `npx playwright test` or `npm run test:e2e`.
 *
 * `BASE_URL` overrides the default `http://localhost:3000` — needed in an
 * SDD worktree, where `make up PORT_OFFSET=<n>` shifts the published frontend
 * port to `3000+n` (`sdd/project.md` §Worktree bootstrap, task 7.3).
 */
const baseURL = process.env.BASE_URL ?? "http://localhost:3000";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  // Deliberately 0 everywhere, including CI (review fix round 1): the login/refresh rate
  // limit (10/min/IP, `RedisLoginThrottle`) is ONE shared budget for the whole suite, on ONE
  // IP (the frontend container's, `login:ip:172.20.0.7` — see tasks.md §Implementation Notes,
  // section 4, "El presupuesto de login del backend es de toda la suite E2E"). A single full
  // pass already runs close to that budget; a Playwright retry re-runs every navigation in the
  // failed test, not just its logins, and `incident.spec.ts`'s own throttle-recovery helpers
  // (`visit`/`loginOnce`) assume a budget that has not already been spent once by the first
  // attempt. Counting navigations precisely enough to make a retry safe would be new
  // machinery for a suite that is not flaky — a real failure should fail loud, not be
  // masked by a retry that itself risks a second round of 429s.
  retries: 0,
  workers: 1,
  reporter: process.env.CI ? "line" : "list",
  // Multi-page flows (login → dashboard → reassign; accept → checklist →
  // photo upload; triage → assign → resolve → approval) run several
  // navigations and API round-trips per test, hence the generous per-test
  // ceiling — well above Vitest's near-instant component tests.
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
