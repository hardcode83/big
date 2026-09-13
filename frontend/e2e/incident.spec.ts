import {
  expect,
  test,
  type Browser,
  type BrowserContext,
  type Locator,
  type Page,
} from "@playwright/test";

import { credentialsFor, loginAs, type Role } from "./fixtures/auth";
import {
  apiLogin,
  assignIncident,
  cancelLingeringIncidents,
  classifyIncident,
  ensureGuestPortalToken,
  getIncident,
  listOwnerApprovals,
  listUsers,
  ownerApprovalThresholdEur,
  propertyForIncidentCycle,
  propertyOperationalState,
  reportGuestIncident,
  resolveIncident,
  type ApiSession,
  type SeedPropertySummary,
} from "./fixtures/seed-context";

/**
 * R4 — the incident cycle, end to end (tasks 4.1, 4.2, 4.3).
 *
 * **Three tests, one continuous story, in order** (`test.describe.serial`),
 * because the cycle is genuinely sequential *and* because it spans three roles:
 * a Playwright `page` carries one session, so the manager, the technician and
 * the owner each get their own test rather than one test logging in and out
 * three times. 4.1 and 4.2 share a single `CRITICAL` incident — 4.2 is the
 * second half of the same journey — while 4.3 opens its own, deliberately
 * cheaper-to-classify one, because the two cases need costs on opposite sides
 * of the tenant's approval threshold and one incident cannot be both.
 *
 * Where the data comes from, and why none of it is invented:
 *
 * - **The incident is reported by a guest, anonymously.** `maintenance` exposes
 *   no `POST /incidents` at all (`incidents_router.py`: "There is deliberately
 *   no `POST /incidents`"); every incident comes from a declared source, and
 *   `POST /api/v1/guest/incident/{token}` is the one a test can drive end to
 *   end. `ensureGuestPortalToken` mints the credential through the manager's
 *   real endpoint.
 * - **Classification is not synchronous.** `docs/maintenance.md` §El job de
 *   clasificación: nothing classifies inside the creating request, on purpose —
 *   its only writer is an anonymous caller from the internet. The two ways in
 *   are the `classify_incidents` job (beat, every 5 min) and
 *   `POST /incidents/{id}/classify`. 4.1 clicks the latter in the manager's
 *   screen, so the assertion is about the product and not about waiting on a
 *   scheduler.
 * - **`CRITICAL` is the classifier's verdict, not a manual choice.**
 *   `RuleBasedIncidentClassifier` maps category → severity, and `SAFETY` is the
 *   only category it rates `CRITICAL` (`_SEVERITIES` in
 *   `backend/app/maintenance/infrastructure/classifier.py`). The report below
 *   names three `SAFETY` keywords — `gas`, `humo`, `alarma` — which is two more
 *   than the one hit that would leave confidence below the tenant's 0.75 and
 *   the incident `OPEN` for human triage.
 *
 * Selectors follow the discipline section 3 set: **nothing keys off a UI
 * string**, because the locale is i18next's to choose and an ES/EN literal
 * would be the first thing to break. What the spec keys off instead is
 * structure (`aria-labelledby`, `data-slot`, stable `id`s, the fixed source
 * order of an action bar) and, in one place, a backend constant that is
 * deliberately not translated — see 4.1's `ai_summary` assertion.
 */

/**
 * Stamped into every title this spec reports, and load-bearing twice over.
 *
 * `SPEC_MARKER` is what `cancelLingeringIncidents` keys on, so the sweep in
 * `beforeAll` can only ever reach incidents this spec created. `RUN_TAG` makes
 * each run's titles unique, which is what lets 4.3 find its own row in
 * `/approvals` rather than a previous run's.
 *
 * Neither leaks into the classifier's verdict: `_normalise` in
 * `classifier.py` splits on `[a-z0-9]+`, and none of `e2e`, `incident`, `spec`
 * or a run of digits appears in `_KEYWORDS`.
 */
const SPEC_MARKER = "[e2e-incident-spec";
const RUN_TAG = `${SPEC_MARKER} ${Date.now()}]`;

/**
 * Three `SAFETY` keywords, so `RuleBasedIncidentClassifier` returns its
 * `_STRONG_CONFIDENCE` (0.95) — comfortably over the tenant's
 * `ai_confidence_threshold` of 0.75 — and therefore `CLASSIFIED`/`CRITICAL`
 * rather than an `OPEN` incident carrying a low-confidence guess.
 */
const CRITICAL_REPORT = {
  title: `Olor a gas y humo en la cocina ${RUN_TAG}`,
  description: "Hay humo y huele a gas. La alarma no para de sonar.",
};

/**
 * Two `APPLIANCE` keywords (`nevera`, `horno`) → `MEDIUM`. Deliberately not
 * `SAFETY`: 4.3 is about the cost gate, and a second `CRITICAL` incident would
 * park the flat in `CRITICAL_INCIDENT` again for reasons that have nothing to
 * do with the requirement under test. Nothing here reaches into another
 * category — in particular no water word, which would make it `HIGH`.
 */
const OVER_THRESHOLD_REPORT = {
  title: `La nevera y el horno no funcionan ${RUN_TAG}`,
  description: "La nevera no enfria nada y el horno tampoco calienta.",
};

/**
 * The one constant `RuleBasedIncidentClassifier` writes to `incidents.ai_summary`
 * for a `SAFETY` verdict (`_SUMMARIES` in `classifier.py`).
 *
 * It is the spec's proof that the *adapter* ran, and it is the one visible
 * string the spec is allowed to match on: it is **not** i18n. The summary is
 * drawn from a closed English vocabulary the adapter declares and
 * `IncidentClassification` enforces, precisely so no path exists from the
 * guest's prose to that column (rule 11 of `sdd/steering/security.md`). A
 * translated status badge would have proved only that some status changed;
 * this proves which adapter produced it.
 */
const SAFETY_AI_SUMMARY = "Possible safety hazard reported at the property";

/** Under the tenant threshold for 4.1/4.2 — the close must go straight through. */
const UNDER_THRESHOLD_COST = "45.50";
const RESOLVE_MATERIALS = "Detector de gas y junta de repuesto";

/** Shared across the three tests, in order. */
let managerSession: ApiSession;
let property: SeedPropertySummary;
/** The flat's state before anything happened, which the cycle must restore. */
let baselineState: string;
let technicianId: string;
let criticalIncidentId: string;
let thresholdEur: number;

test.beforeAll(async () => {
  const { email, password } = credentialsFor("PROPERTY_MANAGER");
  managerSession = await apiLogin(email, password);

  // Before anything is measured: close out whatever an aborted run left live.
  // A leftover `SAFETY` report is not inert — `classify_incidents` reaches it
  // within five minutes and pins the flat to `CRITICAL_INCIDENT` for good,
  // which would then be captured below as this run's "baseline".
  await cancelLingeringIncidents(managerSession, SPEC_MARKER);

  property = await propertyForIncidentCycle(managerSession);
  baselineState = property.current_operational_state;
  thresholdEur = await ownerApprovalThresholdEur(managerSession);

  const technicians = (await listUsers(managerSession, "TECHNICIAN")).filter(
    (user) => user.status === "ACTIVE",
  );
  const seeded = credentialsFor("TECHNICIAN");
  const technician = technicians.find(
    (user) => user.email.toLowerCase() === seeded.email.toLowerCase(),
  );
  if (!technician) {
    throw new Error(
      `incident.spec: no ACTIVE TECHNICIAN with the seeded address ${seeded.email} ` +
        `(found: ${technicians.map((u) => u.email).join(", ") || "none"}). The cycle has to be ` +
        "driven by the one technician whose password the suite knows — run `make seed-demo`.",
    );
  }
  technicianId = technician.id;
});

/**
 * The manager's action bar on `/incidents/[id]`.
 *
 * `ManagerIncidentActions` is the only `<section>` inside the detail article
 * that holds a `<button>` — every other block is a read-only `<dl>` — and its
 * sheets/dialogs are Radix-portalled to `document.body` when open, so they never
 * land inside this locator. The buttons come out in the fixed source order of
 * `manager-incident-actions.tsx`, filtered by `MANAGER_ACTIONS[status]`
 * (`features/incidents/lib/manager-actions.ts`):
 *
 *   OPEN        → classify, triage, cancel
 *   CLASSIFIED  → assign,   triage, cancel
 *
 * so `nth(0)` is "advance the cycle" in both, exactly the convention section 3
 * documented for the cleaner's action bar.
 */
function managerActionBar(page: Page): Locator {
  return page
    .locator('article[aria-labelledby="incident-heading"] section')
    .filter({ has: page.locator("button") });
}

/**
 * The submit button of an open sheet/dialog, without touching its label.
 *
 * Both `AssignSheet` and `TriageSheet` render exactly one control carrying
 * `aria-busy={mutation.isPending}`, which React serialises as `aria-busy="false"`
 * while idle. The sheet's own close affordance has no such attribute, so this
 * picks the confirm button and nothing else.
 */
function dialogSubmit(page: Page): Locator {
  return page.getByRole("dialog").locator("button[aria-busy]");
}

/**
 * The operational-state badge on a property's dashboard card.
 *
 * `PropertyCard` labels each card `property-card-<propertyId>` and puts
 * `PropertyStateBadge` in its `<header>`; `Badge` renders a
 * `<span data-slot="badge">`. The badge's classes are the *only* signal the
 * dashboard gives for PRD §9.1's colour — `TONE_BADGE_CLASS`
 * (`lib/ui/status-tone.ts`) maps the `red` tone, which
 * `components/property-state-badge.tsx` assigns to `CRITICAL_INCIDENT` and to
 * nothing else, onto the `state-error` token. Hence the regex below: it is the
 * rendered form of "aparece en rojo", read off the table the app actually uses
 * rather than a class name guessed from the outside.
 */
function dashboardStateBadge(page: Page, propertyId: string): Locator {
  return page
    .locator(`[aria-labelledby="property-card-${propertyId}"]`)
    .locator('header [data-slot="badge"]');
}

const RED_BADGE = /bg-state-error\//;

/**
 * One long-lived browser context per role, each **logged in exactly once** for
 * the whole file. This is not an optimisation; the spec does not pass without
 * it.
 *
 * `RedisLoginThrottle` (`backend/app/auth/infrastructure/throttle.py`) counts
 * attempts in `login:ip:<ip>` and refuses past `login_rate_limit_per_minute` —
 * **10**, in a fixed 60-second window (`EXPIRE ... NX`, so the window does not
 * slide). The comment on that counter states the part that decides the shape of
 * this file: *"With no trusted client-IP header today every request arrives
 * with the same IP"*. The budget is therefore not per-actor, not per-test and
 * not even per-spec — the whole E2E suite shares ten logins a minute. This file
 * spans three roles over three tests; a `loginAs` per actor per test spends
 * seven of the ten by itself, which is exactly how the owner's login first
 * failed here, showing the form's generic "no se ha podido iniciar sesión".
 *
 * **Kept open rather than snapshotted**, which was the first attempt and does
 * not work: the session's refresh token rotates (the `fam` claim is a token
 * family), so a `storageState()` captured at login is stale the moment the live
 * context refreshes, and restoring it lands on `/login`. Holding the context
 * open keeps the session that is actually current. They are closed in
 * `afterAll`.
 *
 * Three logins for the file, whoever asks and in whatever order.
 */
const roleContexts = new Map<Role, BrowserContext>();

/**
 * The counter's window, plus a margin. `IP_WINDOW_SECONDS` is 60 and the key is
 * set with `EXPIRE ... NX`, so it lapses outright rather than sliding — waiting
 * it out is all that is needed, and waiting it out *once* is enough.
 */
const LOGIN_WINDOW_MS = 65_000;

/**
 * **The budget is not just logins — it is logins _plus every page load_**, and
 * that is the thing to know before touching this file or adding a fourth spec.
 *
 * `RefreshTokenUseCase` spends the *same* counter as `LoginUseCase`, on purpose
 * and with the reasoning written next to it: *"The SAME bucket as login on
 * purpose, not a second one... splitting it would let a caller spend two
 * budgets"*. Its estimate of the cost — *"a legitimate refresh is a few per hour"*
 * — holds for a person driving an SPA, where the access token lives in memory
 * across client-side routing. It does not hold for Playwright: every
 * `page.goto` is a full document load, which drops the in-memory token and
 * makes the app refresh from the httpOnly cookie. **One navigation, one unit of
 * the ten.**
 *
 * And they all land on one key. Measured here: `login:ip:172.20.0.7` — the
 * *frontend container's* address, because the browser talks to Next.js and
 * Next.js proxies to the backend — observed at 9 of 10 with 40s left. Calls
 * made from Node against `BACKEND_URL` arrive from the host instead and spend a
 * different counter, which is why the API helpers in `seed-context.ts` are free
 * and the browser steps are not.
 *
 * So the suite as a whole runs near the ceiling, and a back-to-back rerun sits
 * over it. Two distinct symptoms follow, and `visit` below handles both because
 * only the first one looks like a login failure:
 *
 * 1. the login itself is refused — the form shows its generic message and
 *    `loginAs` times out waiting for the landing URL;
 * 2. **the login succeeds and the _next_ navigation bounces to `/login`** —
 *    the session is real, its refresh was refused. This is the confusing one:
 *    it surfaces as an assertion failing against the login page, pointing
 *    nowhere near a rate limit.
 *
 * Waiting the window out is the honest response: the control is production
 * behaviour doing its job, not a defect in what is under test, and the wait
 * lets it lapse rather than hammering it. Bounded to one retry, so a real auth
 * regression still fails the run, with the cause named.
 */
async function recoverFromThrottle(page: Page, role: Role): Promise<void> {
  test.setTimeout(180_000);
  await page.waitForTimeout(LOGIN_WINDOW_MS);
  await loginAs(page, role);
}

async function loginOnce(page: Page, role: Role): Promise<void> {
  try {
    await loginAs(page, role);
  } catch (first) {
    try {
      await recoverFromThrottle(page, role);
    } catch {
      throw new Error(
        `incident.spec: ${role} could not log in, twice, ${LOGIN_WINDOW_MS}ms apart. The likely ` +
          "cause is the shared `login:ip:<frontend container>` counter (10/min, login AND " +
          "refresh) — see the note on `recoverFromThrottle`. Causa original: " +
          `${first instanceof Error ? first.message : String(first)}`,
      );
    }
  }
}

/**
 * How long to let a navigation declare itself before believing it stuck.
 *
 * The bounce is **not** visible when `goto` resolves: the document loads at the
 * requested URL, the app then refreshes from the cookie, and only when that
 * call answers `429` does it route to `/login`. Checking `page.url()` straight
 * after `goto` therefore always reads the *requested* path — which is how the
 * first version of this helper watched a run bounce and reported it as "the
 * manager's action bar has 0 buttons".
 */
const BOUNCE_GRACE_MS = 3_000;

/** Navigate, and treat an unexpected landing on `/login` as symptom 2 above. */
async function visit(page: Page, role: Role, path: string): Promise<void> {
  for (let attempt = 0; attempt < 2; attempt++) {
    await page.goto(path);
    const bounced = await page
      .waitForURL(/\/login(\?|$)/, { timeout: BOUNCE_GRACE_MS })
      .then(
        () => true,
        () => false,
      );
    if (!bounced) {
      return;
    }
    await recoverFromThrottle(page, role);
  }
  throw new Error(
    `incident.spec: ${role} was bounced to /login on the way to ${path}, twice, ` +
      `${LOGIN_WINDOW_MS}ms apart. See the note on \`recoverFromThrottle\`.`,
  );
}

async function withRole(
  browser: Browser,
  role: Role,
  body: (page: Page, go: (path: string) => Promise<void>) => Promise<void>,
): Promise<void> {
  let context = roleContexts.get(role);
  if (!context) {
    context = await browser.newContext();
    roleContexts.set(role, context);
    await loginOnce(await context.newPage(), role);
  }
  const [page] = context.pages();
  await body(page, (path) => visit(page, role, path));
}

test.afterAll(async () => {
  for (const context of roleContexts.values()) {
    await context.close();
  }
  roleContexts.clear();
});

test.describe.serial("R4 — ciclo de incidencia", () => {
  test("4.1 el huésped reporta, RuleBasedIncidentClassifier clasifica y el manager tría y asigna desde /incidents/[id]", async ({
    browser,
  }) => {
    const token = await ensureGuestPortalToken(managerSession, property.id);
    const reported = await reportGuestIncident(token, CRITICAL_REPORT);
    criticalIncidentId = reported.id;

    // Born OPEN and unclassified: the creating request never calls the
    // classifier (`docs/maintenance.md` §El job de clasificación).
    //
    // "Unclassified" is `ai_summary`/`ai_classification` being empty, **not**
    // `category`/`severity` being null — measured here, and it matches what
    // `docs/maintenance.md` says about the cleaner's route ("La incidencia nace
    // MEDIUM"): the columns are not nullable and a new incident carries the
    // entity's defaults, `OTHER`/`MEDIUM`. Asserting the defaults rather than
    // nulls is what makes the post-classify assertions below mean something —
    // `MEDIUM` → `CRITICAL` is a change the adapter caused.
    expect(reported.status).toBe("OPEN");
    const asCreated = await getIncident(managerSession, criticalIncidentId);
    expect(asCreated.ai_summary).toBeNull();
    expect(asCreated.category).toBe("OTHER");
    expect(asCreated.severity).toBe("MEDIUM");
    expect(asCreated.property_id).toBe(property.id);

    await withRole(browser, "PROPERTY_MANAGER", async (page, go) => {
      await go(`/incidents/${criticalIncidentId}`);

      // OPEN offers classify / triage / cancel.
      const actions = managerActionBar(page);
      await expect(actions.locator("button")).toHaveCount(3);

      // --- the classifier, run from the manager's screen ---
      await actions.locator("button").nth(0).click();

      // The adapter's own closed-vocabulary summary, rendered by
      // `DetailMetadataBlock`. Nothing but a real `RuleBasedIncidentClassifier`
      // verdict puts this string on the page.
      await expect(page.getByText(SAFETY_AI_SUMMARY)).toBeVisible();

      const classified = await getIncident(managerSession, criticalIncidentId);
      expect(classified.status).toBe("CLASSIFIED");
      expect(classified.category).toBe("SAFETY");
      expect(classified.severity).toBe("CRITICAL");
      expect(classified.ai_summary).toBe(SAFETY_AI_SUMMARY);

      // A CRITICAL verdict moves the flat, through the state machine.
      expect(await propertyOperationalState(managerSession, property.id)).toBe(
        "CRITICAL_INCIDENT",
      );

      // --- triage ---
      // CLASSIFIED offers assign / triage / cancel, so triage is nth(1).
      await expect(actions.locator("button")).toHaveCount(3);
      await actions.locator("button").nth(1).click();

      const triageDialog = page.getByRole("dialog");
      await expect(triageDialog).toBeVisible();
      // Estimated cost only, deliberately under the threshold: the severity and
      // category selects keep the classifier's verdict, which R4.2 still needs,
      // and an estimate over the threshold would open the *other* owner-approval
      // gate (`related_type=INCIDENT`) — 4.3's subject is the one at close time.
      const estimated = (thresholdEur / 2).toFixed(2);
      await triageDialog.locator('input[type="number"]').fill(estimated);
      await dialogSubmit(page).click();
      await expect(triageDialog).toBeHidden();

      const triaged = await getIncident(managerSession, criticalIncidentId);
      expect(Number(triaged.estimated_cost)).toBeCloseTo(Number(estimated), 2);
      // Annotating a CLASSIFIED incident transitions nothing, and the severity
      // the classifier chose is untouched.
      expect(triaged.status).toBe("CLASSIFIED");
      expect(triaged.severity).toBe("CRITICAL");

      // --- assign ---
      await actions.locator("button").nth(0).click();
      const assignDialog = page.getByRole("dialog");
      await expect(assignDialog).toBeVisible();
      await assignDialog.locator("select").selectOption(technicianId);
      await dialogSubmit(page).click();
      await expect(assignDialog).toBeHidden();

      const assigned = await getIncident(managerSession, criticalIncidentId);
      expect(assigned.status).toBe("ASSIGNED");
      expect(assigned.assigned_technician_id).toBe(technicianId);
    });
  });

  test("4.2 el técnico acepta y resuelve desde /tech/incidents/[id]; la propiedad está en rojo en el dashboard mientras la CRITICAL sigue abierta", async ({
    browser,
  }) => {
    // --- red while it is open (R4.2) ---
    await withRole(browser, "PROPERTY_MANAGER", async (managerPage, go) => {
      await go("/dashboard");
      await expect(dashboardStateBadge(managerPage, property.id)).toHaveClass(
        RED_BADGE,
      );
    });

    // --- the technician's cycle (R4.1) ---
    await withRole(browser, "TECHNICIAN", async (page, go) => {
      await go(`/tech/incidents/${criticalIncidentId}`);

      // `TECH_ACTIONS` (`features/tech/lib/tech-actions.ts`) fixes the order:
      // ASSIGNED → [accept, reject], ACCEPTED → [en-route, reject]. The first
      // button advances the cycle; the count is what proves which state the
      // screen is in.
      const cycleButtons = page.locator("main button");
      await expect(cycleButtons).toHaveCount(2);
      await cycleButtons.nth(0).click();
      await expect
        .poll(async () => (await getIncident(managerSession, criticalIncidentId)).status)
        .toBe("ACCEPTED");

      await expect(cycleButtons).toHaveCount(2);
      await cycleButtons.nth(0).click();
      await expect
        .poll(async () => (await getIncident(managerSession, criticalIncidentId)).status)
        .toBe("IN_PROGRESS");

      // --- the close, with cost and materials ---
      // IN_PROGRESS replaces the second cycle button with `TechResolveForm`,
      // which owns the two stable ids in this screen.
      await page.locator("#tech-final-cost").fill(UNDER_THRESHOLD_COST);
      await page.locator("#tech-materials").fill(RESOLVE_MATERIALS);
      await page.locator('form:has(#tech-final-cost) button[type="submit"]').click();

      await expect
        .poll(async () => (await getIncident(managerSession, criticalIncidentId)).status)
        .toBe("RESOLVED");
    });

    const resolved = await getIncident(managerSession, criticalIncidentId);
    expect(Number(resolved.final_cost)).toBeCloseTo(Number(UNDER_THRESHOLD_COST), 2);
    expect(resolved.materials).toBe(RESOLVE_MATERIALS);
    // The close was accepted: a cost over the threshold would have parked the
    // incident in AWAITING_OWNER_APPROVAL with `resolved_at` still null — which
    // is exactly what 4.3 exercises.
    expect(resolved.resolved_at).not.toBeNull();
    expect(resolved.owner_approval_required).toBe(false);

    // --- and no longer red once it is closed ---
    // `after_incident_resolution` recomputes the flat from the incidents still
    // active, so this is the same round trip the baseline records.
    expect(await propertyOperationalState(managerSession, property.id)).toBe(
      baselineState,
    );
    await withRole(browser, "PROPERTY_MANAGER", async (managerPage, go) => {
      await go("/dashboard");
      await expect(dashboardStateBadge(managerPage, property.id)).not.toHaveClass(
        RED_BADGE,
      );
    });
  });

  test("4.3 un coste sobre el umbral del tenant abre un OwnerApproval que la propietaria responde en /approvals", async ({
    browser,
  }) => {
    // Setup through the API: the manager half of the cycle is 4.1's subject and
    // is not re-driven here. What 4.3 is about starts at the close.
    const token = await ensureGuestPortalToken(managerSession, property.id);
    const reported = await reportGuestIncident(token, OVER_THRESHOLD_REPORT);
    const incidentId = reported.id;

    const classified = await classifyIncident(managerSession, incidentId);
    // MEDIUM: no property transition, so this case leaves the dashboard alone.
    expect(classified.severity).toBe("MEDIUM");
    expect(await propertyOperationalState(managerSession, property.id)).toBe(
      baselineState,
    );
    await assignIncident(managerSession, incidentId, technicianId);

    // --- the technician closes, over the threshold ---
    const overThresholdCost = (thresholdEur + 150).toFixed(2);
    await withRole(browser, "TECHNICIAN", async (page, go) => {
      await go(`/tech/incidents/${incidentId}`);

      const cycleButtons = page.locator("main button");
      await expect(cycleButtons).toHaveCount(2);
      await cycleButtons.nth(0).click(); // accept
      await expect
        .poll(async () => (await getIncident(managerSession, incidentId)).status)
        .toBe("ACCEPTED");
      await expect(cycleButtons).toHaveCount(2);
      await cycleButtons.nth(0).click(); // en-route
      await expect
        .poll(async () => (await getIncident(managerSession, incidentId)).status)
        .toBe("IN_PROGRESS");

      await page.locator("#tech-final-cost").fill(overThresholdCost);
      await page.locator('form:has(#tech-final-cost) button[type="submit"]').click();

      await expect
        .poll(async () => (await getIncident(managerSession, incidentId)).status)
        .toBe("AWAITING_OWNER_APPROVAL");
    });

    const parked = await getIncident(managerSession, incidentId);
    // D11: the cost is recorded and the close is *not* accepted — the
    // technician said what it cost and the system did not close the incident.
    expect(Number(parked.final_cost)).toBeCloseTo(Number(overThresholdCost), 2);
    expect(parked.resolved_at).toBeNull();
    expect(parked.owner_approval_required).toBe(true);

    const pending = await listOwnerApprovals(managerSession, "PENDING");
    const approval = pending.find((row) => row.incident?.id === incidentId);
    expect(approval, "the close over the threshold must open an OwnerApproval").toBeTruthy();
    // The close-time gate, not the triage-time one.
    expect(approval!.related_type).toBe("MAINTENANCE_COST");
    expect(Number(approval!.amount)).toBeCloseTo(Number(overThresholdCost), 2);

    // --- the owner answers it in /approvals ---
    await withRole(browser, "TENANT_OWNER", async (ownerPage, go) => {
      await go("/approvals");

      // `RequestCell` renders the incident's own title, which is this run's
      // string and not a translated one — the row handle the queue offers.
      const row = ownerPage.locator("tr").filter({ hasText: OVER_THRESHOLD_REPORT.title });
      await expect(row).toHaveCount(1);
      await expect(row).toContainText(overThresholdCost);

      // The decision cell renders approve then reject, in that order, and it
      // renders at all only for `RESPOND_OWNER_APPROVALS` — the owner's alone.
      await row.locator("button").nth(0).click();

      await expect
        .poll(async () =>
          (await listOwnerApprovals(managerSession, "PENDING")).some(
            (item) => item.incident?.id === incidentId,
          ),
        )
        .toBe(false);
    });

    const approved = await getIncident(managerSession, incidentId);
    // Approving the real cost does **not** close the incident: it returns it to
    // IN_PROGRESS and the technician repeats the close, so `resolved_at` keeps
    // meaning "the technician called it done" (`docs/maintenance.md`).
    expect(approved.status).toBe("IN_PROGRESS");
    expect(Number(approved.approved_cost)).toBeCloseTo(Number(overThresholdCost), 2);
    expect(approved.resolved_at).toBeNull();

    // Finish it so the run leaves nothing parked. The close itself is 4.2's
    // subject and was already driven through the UI there; here it is cleanup.
    const closed = await resolveIncident(managerSession, incidentId, overThresholdCost);
    expect(closed.status).toBe("RESOLVED");
    expect(await propertyOperationalState(managerSession, property.id)).toBe(
      baselineState,
    );
  });
});
