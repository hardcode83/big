import { Buffer } from "node:buffer";

import { expect, test, type Locator } from "@playwright/test";

import { credentialsFor, loginAs } from "./fixtures/auth";
import {
  apiLogin,
  assignCleaningTask,
  createCleaningTask,
  ensurePropertyAwaitingCleaning,
  ensureUser,
  getCleaningTask,
  listProperties,
  listUsers,
  propertyOperationalState,
  type ApiSession,
  type SeedUser,
} from "./fixtures/seed-context";

/**
 * R3 — the full cleaning cycle, end to end against the real stack.
 *
 * `sdd/steering/testing.md` asks for the *complete* flow, so this file drives
 * every step of `docs/cleaning.md` §El ciclo that a person performs:
 * reassignment from `/cleaning` (R3.2), then accept → start → checklist →
 * the required photo of every category → close, from `/cleaner` and
 * `/cleaner/tasks/[id]` (R3.1), and finally the property's operational state.
 *
 * **Two tests, one task, in order** (`test.describe.serial`): R3.2 happens
 * "before it's accepted", so it has to run first and it leaves the task
 * assigned to the seeded `CLEANER`, which is the actor R3.1 then logs in as.
 * `playwright.config.ts` already pins `workers: 1` / `fullyParallel: false`,
 * so no other spec mutates the tenant underneath.
 */

/**
 * A real 1×1 PNG (70 bytes), inline rather than a checked-in binary so the
 * bytes stay reviewable. `POST /cleaning-tasks/{id}/photos` decides the format
 * from the **bytes**, never from the declared `Content-Type`
 * (`docs/cleaning.md` §Subir), so this has to be a genuine PNG signature —
 * and being a genuine image is also what lets the gallery's `<img>` decode it,
 * which is the assertion at the end of the cycle.
 */
const PIXEL_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

/**
 * The cleaner a reassignment moves the task **away** from.
 *
 * `make seed-demo` creates exactly one cleaner, and a reassignment needs two —
 * `AssignCleanerControl` will not confirm a pick that equals the current
 * assignee. The seeded one is kept as the *destination* on purpose: it is the
 * only cleaner whose password the suite knows (`SEED_CLEANER_*`), so it is the
 * only one that can then log in and run R3.1's half of the cycle.
 *
 * Fixed address, created at most once per tenant — see `ensureUser`.
 */
const RELIEF_CLEANER = {
  name: "Relevo E2E",
  email: "e2e-cleaner-relief@hardening-e2e.local",
  role: "CLEANER",
};

/**
 * Where `CLEANING_COMPLETED` can leave a flat, straight from
 * `PropertyStateMachine._POLICY`: `(CLEANING_IN_PROGRESS, CLEANING_COMPLETED)
 * → {READY_FOR_NEXT_GUEST, AWAITING_CHECKIN, VACANT_READY}`. Which of the
 * three it is depends on the flat's reservations and is resolved by
 * `ContextualStateResolver`, so the assertion is membership and not one
 * literal — the contract is the set.
 *
 * These are also exactly the three 🟢 green states of `docs/dashboard.md`
 * §Colores de estado, which is what "the property is ready again" means on the
 * dashboard.
 */
const READY_AFTER_CLEANING = ["READY_FOR_NEXT_GUEST", "AWAITING_CHECKIN", "VACANT_READY"];

/** Properties the cycle can be driven from — see `ensurePropertyAwaitingCleaning`. */
const CYCLE_START_STATES = ["AWAITING_CLEANING", "VACANT_READY", "READY_FOR_NEXT_GUEST"];

/**
 * Who `/cleaning` says is assigned right now, read from the row's own cell.
 *
 * `CleaningTaskRow` renders the resolved name as a **bare text node** inside
 * the cleaner `Field`'s value `<span>`, immediately followed by
 * `AssignCleanerControl`'s own markup — and that control lists *every* active
 * cleaner as an `<option>`. So the span's overall text contains both names
 * whoever is assigned, and only its direct text nodes answer the question.
 *
 * Returns `""` for the three degraded shapes of `IdentityValue`
 * («Sin asignar», the loading marker, «Identidad no disponible»): all three
 * render an element, never a bare text node.
 */
async function assignedCleanerName(row: Locator, taskId: string): Promise<string> {
  return row.evaluate((li, selectId) => {
    const select = li.querySelector(`#${CSS.escape(selectId)}`);
    const cell = select?.closest("span") ?? null;
    if (!cell) {
      return "";
    }
    return Array.from(cell.childNodes)
      .filter((node) => node.nodeType === Node.TEXT_NODE)
      .map((node) => node.textContent ?? "")
      .join("")
      .trim();
  }, `assign-cleaner-${taskId}`);
}

test.describe.serial("R3 — ciclo de limpieza", () => {
  let manager: ApiSession;
  let seededCleaner: SeedUser;
  let reliefCleaner: SeedUser;
  let propertyId: string;
  let taskId: string;

  test.beforeAll(async () => {
    manager = await apiLogin(
      credentialsFor("PROPERTY_MANAGER").email,
      credentialsFor("PROPERTY_MANAGER").password,
    );
    // Creating a user needs `MANAGE_USERS`, which only `TENANT_OWNER` holds
    // (`_USER_MANAGE` in `backend/app/auth/domain/policy.py`); the manager can
    // only read the roster.
    const owner = await apiLogin(
      credentialsFor("TENANT_OWNER").email,
      credentialsFor("TENANT_OWNER").password,
    );

    const cleanerEmail = credentialsFor("CLEANER").email.toLowerCase();
    const found = (await listUsers(manager, "CLEANER")).find(
      (user) => user.email.toLowerCase() === cleanerEmail,
    );
    expect(
      found,
      `No hay ningún CLEANER con el email ${cleanerEmail} en el tenant — corre \`make seed-demo\`.`,
    ).toBeTruthy();
    seededCleaner = found!;
    reliefCleaner = await ensureUser(owner, RELIEF_CLEANER);

    // A flat the cycle can start from. Not `firstProperty()`: the cycle has a
    // hard precondition on the operational state (only `AWAITING_CLEANING`
    // admits `CLEANER_ASSIGNED`), and the demo tenant's other flat is parked in
    // `MAINTENANCE_REQUIRED` with a live stay.
    const candidate = (await listProperties(manager)).find((property) =>
      CYCLE_START_STATES.includes(property.current_operational_state),
    );
    expect(
      candidate,
      "Ninguna vivienda del tenant está en " +
        `${CYCLE_START_STATES.join("/")}, así que no se puede sembrar un ciclo de limpieza.`,
    ).toBeTruthy();
    propertyId = candidate!.id;

    await ensurePropertyAwaitingCleaning(manager, propertyId);

    // Fixture 1.5: the task the two tests share, seeded by API in a known
    // state instead of depending on checkout timing.
    const task = await createCleaningTask(manager, { propertyId });
    taskId = task.id;
    expect(task.status).toBe("CREATED");

    // The assignment R3.2 then *re*-assigns away from. Done by API on purpose:
    // what the UI test has to exercise is the reassignment, and a task with no
    // assignee would only let it exercise a first assignment.
    const assigned = await assignCleaningTask(manager, taskId, reliefCleaner.id);
    expect(assigned.status).toBe("ASSIGNED");
    // Assigning a `CREATED` task is also what moves the flat, which is the half
    // of the precondition `docs/cleaning.md` §La primera asignación describes.
    expect(await propertyOperationalState(manager, propertyId)).toBe("CLEANING_SCHEDULED");
  });

  test("3.1 el PROPERTY_MANAGER reasigna la tarea desde /cleaning y el nuevo asignado se refleja", async ({
    page,
  }) => {
    await loginAs(page, "PROPERTY_MANAGER");
    await page.goto("/cleaning");

    // The task is the newest of the tenant and the list opens unfiltered, in
    // `created_at` descending order (`docs/cleaning.md` §Filtrar y paginar), so
    // it is on page 1.
    const row = page.locator(`li:has(h3#cleaning-task-${taskId})`);
    await expect(row).toBeVisible();

    // What the screen says before the reassignment.
    await expect
      .poll(() => assignedCleanerName(row, taskId))
      .toBe(reliefCleaner.name);

    // The control: a `<select>` of active cleaners plus an explicit confirm
    // button (`AssignCleanerControl` — the button is deliberate, a `<select>`
    // navigated with the arrow keys fires `change` on every option it passes).
    // Located structurally, so neither assertion depends on an i18n label.
    const picker = row.locator(`select#assign-cleaner-${taskId}`);
    const confirm = row.locator(`#assign-cleaner-${taskId} + button`);

    await expect(confirm).toBeDisabled(); // nothing picked yet
    await picker.selectOption(seededCleaner.id);
    await expect(confirm).toBeEnabled();
    await confirm.click();

    // The list refetches after an assignment rather than patching the row in
    // memory (`docs/cleaning.md` §Filtrar y paginar), so poll the cell.
    await expect
      .poll(() => assignedCleanerName(row, taskId), {
        message: "la fila de /cleaning no refleja la nueva limpiadora asignada",
      })
      .toBe(seededCleaner.name);

    // ...and the server agrees, which is the half the screen cannot prove
    // ("el frontend oculta, el backend decide").
    const task = await getCleaningTask(manager, taskId);
    expect(task.assigned_cleaner_id).toBe(seededCleaner.id);
    expect(task.status).toBe("ASSIGNED");
    // Re-pointing an already `ASSIGNED` task does not move the flat.
    expect(await propertyOperationalState(manager, propertyId)).toBe("CLEANING_SCHEDULED");
  });

  test("3.2 el CLEANER acepta, completa el checklist, sube las fotos requeridas y cierra la limpieza", async ({
    page,
  }) => {
    // 18 checklist items and 6 photo categories, each one its own mutation and
    // refetch against the real stack — well past the 60 s default.
    test.setTimeout(240_000);

    await loginAs(page, "CLEANER");

    // From her own list at `/cleaner` into the task detail.
    const taskLink = page.locator(`a[href="/cleaner/tasks/${taskId}"]`);
    await expect(taskLink).toBeVisible();
    await taskLink.click();
    await page.waitForURL(`**/cleaner/tasks/${taskId}`);

    // Every block is located by the `aria-labelledby` id its section declares —
    // stable, and independent of the rendered locale.
    const actionBar = page.locator('section[aria-labelledby="cleaner-action-bar-heading"]');
    const checklist = page.locator('section[aria-labelledby="cleaner-checklist-heading"]');
    const photos = page.locator('section[aria-labelledby="cleaner-photo-reqs-heading"]');
    const gallery = page.locator('section[aria-labelledby="cleaner-gallery-heading"]');

    // `CLEANER_ACTIONS` (`features/cleaner/lib/cleaner-actions.ts`) is what
    // decides the bar's buttons, in this DOM order:
    //   ASSIGNED → [aceptar, rechazar] · ACCEPTED → [iniciar] · IN_PROGRESS →
    //   [cerrar] (+ the incident panel, which is rendered after the button row).
    // So the first button is always the one that advances the cycle, and the
    // count is what proves which status the screen is showing.
    const advance = actionBar.getByRole("button").first();

    await expect(actionBar.getByRole("button")).toHaveCount(2); // ASSIGNED
    await advance.click();
    await expect(actionBar.getByRole("button")).toHaveCount(1); // ACCEPTED
    await advance.click();

    // `IN_PROGRESS` is what opens the checklist and the uploads (R5.1/R4.1):
    // every pending item grows a button and every uncovered category an
    // `<input type="file">`.
    const items = await checklist.locator("li").count();
    expect(items).toBeGreaterThan(0);
    await expect(checklist.getByRole("button")).toHaveCount(items);
    expect(await propertyOperationalState(manager, propertyId)).toBe("CLEANING_IN_PROGRESS");

    // The checklist. A ticked item stops offering its button
    // (`CleanerTaskChecklistItem` returns `null` once `completed`), so the
    // count falling by one is the acknowledgement to wait for.
    for (let remaining = items; remaining > 0; remaining -= 1) {
      await checklist.getByRole("button").first().click();
      await expect(checklist.getByRole("button")).toHaveCount(remaining - 1);
    }

    // The photos, one per category the template declares — all of them
    // `required: true` in the demo template, and `POST /complete` refuses while
    // any of them has none (`docs/cleaning.md` §Al cerrar).
    const categories = await photos.locator("li").count();
    expect(categories).toBeGreaterThan(0);
    const fileInputs = photos.locator('input[type="file"]');
    await expect(fileInputs).toHaveCount(categories);

    // The `<input>` is `sr-only`/`aria-hidden` — the visible control is the
    // button that clicks it — and `setInputFiles` drives it directly, which is
    // what a file picker is for. The bytes are the in-memory PNG above: no
    // fixture file on disk and no path for the test to get wrong.
    for (let remaining = categories; remaining > 0; remaining -= 1) {
      await fileInputs.first().setInputFiles({
        name: "cleaning-evidence.png",
        mimeType: "image/png",
        buffer: PIXEL_PNG,
      });
      // A covered category never offers a button again (`uploaded: true` →
      // "Cubierta"), so the input disappearing is the upload's acknowledgement.
      await expect(fileInputs).toHaveCount(remaining - 1);
    }

    // The evidence is served back through the signed URL the API minted —
    // read from the DOM, never rebuilt here (`steering/security.md` #5).
    // Asserting the image actually decoded proves the whole round trip: bytes
    // stored, signature valid, route serving.
    const images = gallery.locator("img");
    await expect(images).toHaveCount(categories);
    await expect
      .poll(() =>
        images.evaluateAll((nodes) =>
          nodes.every((node) => (node as HTMLImageElement).naturalWidth > 0),
        ),
      )
      .toBe(true);

    // Close.
    await expect(actionBar.getByRole("button").first()).toBeEnabled();
    await actionBar.getByRole("button").first().click();

    // The reversible completion panel is the screen's own statement that the
    // close succeeded (`CleanerCompletionPanel`, R7.2).
    await expect(
      page.locator('section[aria-labelledby="cleaner-completion-heading"]'),
    ).toBeVisible();

    const closed = await getCleaningTask(manager, taskId);
    expect(closed.status).toBe("COMPLETED");

    // R3.1's second half: the flat's operational state moves on, to wherever
    // its reservations put it among the three destinations of
    // `CLEANING_COMPLETED` — the 🟢 green band of `docs/dashboard.md`.
    expect(READY_AFTER_CLEANING).toContain(
      await propertyOperationalState(manager, propertyId),
    );
  });
});
