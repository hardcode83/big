import { execFileSync } from "node:child_process";
import { resolve } from "node:path";

import { loadRootEnv, resolveBackendUrl } from "./load-env";

/**
 * API helpers for seeding data a spec needs *beyond* `make seed-demo` — e.g. a
 * `CleaningTask` in an exact starting state — so a test does not depend on
 * timing/ordering of the demo seed to find one. Calls the backend directly
 * (`BACKEND_URL`, default `http://localhost:8000`, derived from
 * `BACKEND_HEALTH_URL` in a `PORT_OFFSET` worktree — see `resolveBackendUrl`),
 * never through the frontend's same-origin proxy: these run from Node in the
 * test process, not from the browser page.
 *
 * Every helper documents the exact endpoint it calls, per task 1.5. Extend
 * this file (do not create a parallel one) as later sections need more seed
 * data — e.g. an incident helper for section 4.
 */

const BACKEND_URL = resolveBackendUrl();

export interface ApiSession {
  accessToken: string;
}

/**
 * `POST /api/v1/auth/login` — authenticates directly against the backend, no
 * browser involved. Pass the result to the other helpers below.
 */
export async function apiLogin(email: string, password: string): Promise<ApiSession> {
  loadRootEnv();
  const response = await fetch(`${BACKEND_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    throw new Error(
      `seed-context.apiLogin: POST /api/v1/auth/login -> ${response.status} ` +
        `${await response.text()}`,
    );
  }
  const body = (await response.json()) as { access_token: string };
  return { accessToken: body.access_token };
}

function authHeaders(session: ApiSession): HeadersInit {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${session.accessToken}`,
  };
}

export interface SeedProperty {
  id: string;
  name: string;
}

/**
 * `GET /api/v1/properties?page=1&per_page=1` — the first property `make
 * seed-demo` created for the authenticated tenant. Specs that need *a*
 * property id (not a specific one) call this instead of hardcoding a seeded
 * UUID, which would drift the moment `seed_demo.py` changes.
 */
export async function firstProperty(session: ApiSession): Promise<SeedProperty> {
  const response = await fetch(`${BACKEND_URL}/api/v1/properties?page=1&per_page=1`, {
    headers: authHeaders(session),
  });
  if (!response.ok) {
    throw new Error(
      `seed-context.firstProperty: GET /api/v1/properties -> ${response.status} ` +
        `${await response.text()}`,
    );
  }
  const body = (await response.json()) as { data: SeedProperty[] };
  const [property] = body.data;
  if (!property) {
    throw new Error(
      "seed-context.firstProperty: no properties found for this tenant — run `make seed-demo` first.",
    );
  }
  return property;
}

export interface CreateCleaningTaskInput {
  propertyId: string;
  reservationId?: string;
  scheduledStart?: string;
  scheduledEnd?: string;
}

export interface SeedCleaningTask {
  id: string;
  status: string;
}

/**
 * `POST /api/v1/cleaning-tasks` (`backend/app/cleaning/api/tasks_router.py`
 * `create_cleaning_task`, the hand-created path alongside the automatic
 * `process_checkouts` one) — creates a `CleaningTask` in `PENDING` for the
 * given property, so section 3's spec can seed one in a known state instead
 * of waiting on checkout timing. Caller must be authenticated as a role
 * `ManageDep` accepts (`TENANT_OWNER` / `PROPERTY_MANAGER` — see
 * `fixtures/auth.ts` `credentialsFor`).
 */
export async function createCleaningTask(
  session: ApiSession,
  input: CreateCleaningTaskInput,
): Promise<SeedCleaningTask> {
  const response = await fetch(`${BACKEND_URL}/api/v1/cleaning-tasks`, {
    method: "POST",
    headers: authHeaders(session),
    body: JSON.stringify({
      property_id: input.propertyId,
      reservation_id: input.reservationId ?? null,
      scheduled_start: input.scheduledStart ?? null,
      scheduled_end: input.scheduledEnd ?? null,
    }),
  });
  if (!response.ok) {
    throw new Error(
      `seed-context.createCleaningTask: POST /api/v1/cleaning-tasks -> ${response.status} ` +
        `${await response.text()}`,
    );
  }
  return (await response.json()) as SeedCleaningTask;
}

/**
 * `PATCH /api/v1/cleaning-tasks/{task_id}` (`tasks_router.py`
 * `assign_cleaning_task`, `MANAGE_CLEANING_TASKS` — manager, not owner) — the
 * same endpoint `/cleaning`'s `AssignCleanerControl` calls. Used by
 * `cleaning.spec.ts` to put a task into `ASSIGNED` **before** the spec drives a
 * real *re*-assignment through the UI (R3.2 speaks of reassigning, which needs
 * a previous assignee to move away from).
 *
 * Beware the precondition the backend enforces and `docs/cleaning.md`
 * §«La primera asignación exige la vivienda pendiente de limpieza» spells out:
 * assigning a `CREATED` task also moves the property `AWAITING_CLEANING →
 * CLEANING_SCHEDULED`, so the property must already be in `AWAITING_CLEANING`
 * (see `ensurePropertyAwaitingCleaning` below). Re-pointing an already
 * `ASSIGNED` task moves nothing and has no such precondition.
 */
export async function assignCleaningTask(
  session: ApiSession,
  taskId: string,
  cleanerId: string,
): Promise<SeedCleaningTask> {
  const response = await fetch(`${BACKEND_URL}/api/v1/cleaning-tasks/${taskId}`, {
    method: "PATCH",
    headers: authHeaders(session),
    body: JSON.stringify({ assigned_cleaner_id: cleanerId }),
  });
  if (!response.ok) {
    throw new Error(
      `seed-context.assignCleaningTask: PATCH /api/v1/cleaning-tasks/${taskId} -> ` +
        `${response.status} ${await response.text()}`,
    );
  }
  return (await response.json()) as SeedCleaningTask;
}

export interface SeedCleaningTaskDetail extends SeedCleaningTask {
  assigned_cleaner_id: string | null;
  property_id: string;
  validation_status: string;
}

/** `GET /api/v1/cleaning-tasks/{task_id}` — the task as the backend has it. */
export async function getCleaningTask(
  session: ApiSession,
  taskId: string,
): Promise<SeedCleaningTaskDetail> {
  const response = await fetch(`${BACKEND_URL}/api/v1/cleaning-tasks/${taskId}`, {
    headers: authHeaders(session),
  });
  if (!response.ok) {
    throw new Error(
      `seed-context.getCleaningTask: GET /api/v1/cleaning-tasks/${taskId} -> ` +
        `${response.status} ${await response.text()}`,
    );
  }
  return (await response.json()) as SeedCleaningTaskDetail;
}

export interface CreatedUserWithTemporaryPassword {
  email: string;
  temporaryPassword: string;
}

/**
 * `POST /api/v1/users` (`backend/app/auth/api/users_router.py` `create_user`,
 * requires `MANAGE_USERS` — `TENANT_OWNER`/`PROPERTY_MANAGER` credentials via
 * `session`) — the cheapest realistic way to get a fresh user with
 * `must_change_password: true`: `CreateUserUseCase` always sets that flag
 * (`backend/app/auth/application/user_admin.py:134`, "a fresh temporary
 * password... the flag is what stops it from quietly becoming the account's
 * permanent credential") and returns the one-time temporary password in the
 * response body (never logged, per `docs/auth-account-recovery.md`). Used by
 * `login.spec.ts` (R2.3) instead of resetting a seeded user's password, which
 * would clobber the credentials sections 3/4 rely on.
 *
 * Email is randomised per call so re-running the spec against an already-seeded
 * tenant never collides with a previous run's `409`.
 */
export async function createUserWithTemporaryPassword(
  session: ApiSession,
  role: "PROPERTY_MANAGER" | "CLEANER" | "TECHNICIAN",
): Promise<CreatedUserWithTemporaryPassword> {
  const email = `e2e-must-change-${Date.now()}-${Math.floor(Math.random() * 1e6)}@hardening-e2e.local`;
  const response = await fetch(`${BACKEND_URL}/api/v1/users`, {
    method: "POST",
    headers: authHeaders(session),
    body: JSON.stringify({
      name: "E2E Must Change Password",
      email,
      role,
    }),
  });
  if (!response.ok) {
    throw new Error(
      `seed-context.createUserWithTemporaryPassword: POST /api/v1/users -> ${response.status} ` +
        `${await response.text()}`,
    );
  }
  const body = (await response.json()) as { temporary_password: string };
  return { email, temporaryPassword: body.temporary_password };
}

/**
 * `GET /api/v1/auth/me` — the authenticated user, for the one field the seed
 * helpers need that no other route hands out: `tenant_id`, which
 * `runSimAdvance` below has to pass to the CLI.
 */
export async function apiMe(
  session: ApiSession,
): Promise<{ id: string; tenantId: string; role: string }> {
  const response = await fetch(`${BACKEND_URL}/api/v1/auth/me`, {
    headers: authHeaders(session),
  });
  if (!response.ok) {
    throw new Error(
      `seed-context.apiMe: GET /api/v1/auth/me -> ${response.status} ${await response.text()}`,
    );
  }
  const body = (await response.json()) as { id: string; tenant_id: string; role: string };
  return { id: body.id, tenantId: body.tenant_id, role: body.role };
}

export interface SeedPropertySummary {
  id: string;
  name: string;
  internal_code: string;
  current_operational_state: string;
}

/** `GET /api/v1/properties?page=1&per_page=100` — the tenant's whole portfolio. */
export async function listProperties(
  session: ApiSession,
): Promise<SeedPropertySummary[]> {
  const response = await fetch(`${BACKEND_URL}/api/v1/properties?page=1&per_page=100`, {
    headers: authHeaders(session),
  });
  if (!response.ok) {
    throw new Error(
      `seed-context.listProperties: GET /api/v1/properties -> ${response.status} ` +
        `${await response.text()}`,
    );
  }
  return ((await response.json()) as { data: SeedPropertySummary[] }).data;
}

/**
 * `GET /api/v1/properties/{id}/state` (`dashboard-api`, `docs/dashboard.md`) —
 * the canonical operational state, which is the thing R3.1's "update the
 * property's operational state accordingly" is actually about. Read from the
 * API and not scraped off a dashboard card: the card's colour is a rendering of
 * this value (`docs/dashboard.md` §Colores de estado), not a second source.
 */
export async function propertyOperationalState(
  session: ApiSession,
  propertyId: string,
): Promise<string> {
  const response = await fetch(
    `${BACKEND_URL}/api/v1/properties/${propertyId}/state`,
    { headers: authHeaders(session) },
  );
  if (!response.ok) {
    throw new Error(
      `seed-context.propertyOperationalState: GET /api/v1/properties/${propertyId}/state -> ` +
        `${response.status} ${await response.text()}`,
    );
  }
  return ((await response.json()) as { current_operational_state: string })
    .current_operational_state;
}

export interface SeedUser {
  id: string;
  name: string;
  email: string;
  role: string;
  status: string;
}

/**
 * `GET /api/v1/users?role=<role>&page=1&per_page=100` — needs `READ_USERS`,
 * which `PROPERTY_MANAGER` has (`_USER_READ` in
 * `backend/app/auth/domain/policy.py`); creating one needs `MANAGE_USERS`,
 * which only `TENANT_OWNER` has — see `ensureUser` below.
 */
export async function listUsers(
  session: ApiSession,
  role: string,
): Promise<SeedUser[]> {
  const response = await fetch(
    `${BACKEND_URL}/api/v1/users?role=${role}&page=1&per_page=100`,
    { headers: authHeaders(session) },
  );
  if (!response.ok) {
    throw new Error(
      `seed-context.listUsers: GET /api/v1/users?role=${role} -> ${response.status} ` +
        `${await response.text()}`,
    );
  }
  return ((await response.json()) as { data: SeedUser[] }).data;
}

/**
 * An **idempotent** `POST /api/v1/users` (`MANAGE_USERS` → `TENANT_OWNER`
 * session): creates the user if the tenant does not have it and returns the
 * existing one otherwise, keyed on a **fixed** email.
 *
 * Deliberately different from `createUserWithTemporaryPassword` above, which
 * randomises the address on purpose: this one exists for a *standing* extra
 * actor (`cleaning.spec.ts`'s second cleaner, the one a reassignment moves the
 * task away from — R3.2). A randomised address there would add one more cleaner
 * to the tenant on every run, and the roster is not inert: `process_checkouts`
 * only auto-assigns a new task when the tenant has **exactly one** active
 * cleaner (`docs/cleaning.md` §El ciclo), so a growing roster would silently
 * change how every later run starts.
 *
 * The returned user's `must_change_password` is `true` and its temporary
 * password is not kept: this account is only ever a *target* of an assignment,
 * never a login. Being `ACTIVE` is what `AssignCleaningTaskUseCase` requires of
 * it, and a fresh user is `ACTIVE`.
 */
export async function ensureUser(
  ownerSession: ApiSession,
  input: { name: string; email: string; role: string },
): Promise<SeedUser> {
  const existing = (await listUsers(ownerSession, input.role)).find(
    (user) => user.email.toLowerCase() === input.email.toLowerCase(),
  );
  if (existing) {
    return existing;
  }
  const response = await fetch(`${BACKEND_URL}/api/v1/users`, {
    method: "POST",
    headers: authHeaders(ownerSession),
    body: JSON.stringify({
      name: input.name,
      email: input.email,
      role: input.role,
      preferred_language: "es",
    }),
  });
  if (!response.ok) {
    throw new Error(
      `seed-context.ensureUser: POST /api/v1/users -> ${response.status} ` +
        `${await response.text()}`,
    );
  }
  return ((await response.json()) as { user: SeedUser }).user;
}

/**
 * The marker that makes the checkout-cycle reservation of
 * `ensurePropertyAwaitingCleaning` findable across runs. `external_channel_id`
 * is settable on create and — deliberately — absent from
 * `UpdateReservationRequest`, so it is a stable handle the spec cannot
 * accidentally rewrite.
 */
const CYCLE_RESERVATION_MARKER = "e2e-cleaning-cycle";

interface SeedReservation {
  id: string;
  property_id: string;
  status: string;
  check_in_date: string;
  check_out_date: string;
  external_channel_id: string | null;
}

/**
 * Statuses the clock triggers accept as a stay
 * (`PropertyStateMachine._validate_trigger_preconditions`). Two of them on the
 * same flat, overlapping the same window, is what `AdvancePropertyStatesUseCase`
 * reports as `ambiguous` and refuses to resolve.
 */
const LIVE_RESERVATION_STATUSES = new Set(["CONFIRMED", "CHECKED_IN_ESTIMATED"]);

async function listReservations(session: ApiSession): Promise<SeedReservation[]> {
  const response = await fetch(`${BACKEND_URL}/api/v1/reservations?page=1&per_page=100`, {
    headers: authHeaders(session),
  });
  if (!response.ok) {
    throw new Error(
      `seed-context.listReservations: GET /api/v1/reservations -> ${response.status} ` +
        `${await response.text()}`,
    );
  }
  return ((await response.json()) as { data: SeedReservation[] }).data;
}

/** `YYYY-MM-DD` for an instant, in UTC. */
function utcDate(instant: Date): string {
  return instant.toISOString().slice(0, 10);
}

/**
 * Runs the three clock jobs for one tenant, synchronously, through the CLI the
 * repo already ships: `make sim-advance TENANT=<uuid> [AT=<iso>]` →
 * `python -m app.cli.sim_advance` inside the `backend` container
 * (`check_checkin_windows`, `mark_occupied_estimated`, `process_checkouts`, in
 * that order, all sharing one frozen `now`).
 *
 * This is the one helper in this file that is not an HTTP call, and it is here
 * on purpose (task 1.5 says extend this file rather than fork a parallel one):
 * it is seed data all the same — the three transitions that no API route
 * exposes. `design.md` §Riesgos prescribes exactly this over waiting on the
 * real scheduler: "si un flujo depende de un job periódico, dispararlo a mano
 * con los comandos ya existentes (`make sim-advance`, `make pms-sync`) en vez
 * de esperar al scheduler real" — beat runs each of the three every 5 minutes,
 * so the natural path would cost up to three ticks.
 *
 * `PORT_OFFSET` is derived from the resolved backend URL's port rather than
 * read from the environment: `make` needs it to pick this worktree's compose
 * overlay, and the spec already knows which stack it is talking to (backend
 * `8000+n` ⇒ offset `n`). An unshifted stack yields `""`, which is what the
 * Makefile treats as "no offset" (`OFFSET := $(if $(subst 0,,...))`).
 */
export function runSimAdvance(tenantId: string, at?: string): string {
  const repoRoot = resolve(__dirname, "..", "..", "..");
  const backendPort = Number(new URL(BACKEND_URL).port || "80");
  const offset = backendPort > 8000 ? String(backendPort - 8000) : "";
  const args = ["sim-advance", `TENANT=${tenantId}`];
  if (at) {
    args.push(`AT=${at}`);
  }
  try {
    return execFileSync("make", args, {
      cwd: repoRoot,
      env: { ...process.env, PORT_OFFSET: offset },
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch (error) {
    const details = error instanceof Error ? error.message : String(error);
    throw new Error(
      `seed-context.runSimAdvance: \`make ${args.join(" ")}\` (PORT_OFFSET=${offset || "<none>"}) ` +
        `failed in ${repoRoot}. The stack has to be up (\`make up\`) and the backend container ` +
        `reachable through \`docker compose exec\`. Causa: ${details}`,
    );
  }
}

/** States the cleaning cycle can be driven from, via the clock chain below. */
const CYCLE_START_STATES = new Set(["VACANT_READY", "READY_FOR_NEXT_GUEST"]);

/**
 * Leaves `propertyId` in `AWAITING_CLEANING`, which is the **only** state from
 * which a cleaning can be assigned and therefore the precondition of the whole
 * R3 cycle (`PropertyStateMachine._POLICY`: `AWAITING_CLEANING` +
 * `CLEANER_ASSIGNED` is the single row admitting that trigger).
 *
 * No API route writes an operational state — every transition belongs to the
 * state machine, driven by the clock jobs (`sdd/steering/architecture.md`) — so
 * the only honest way in is the real one: a stay that checks in and then checks
 * out. This helper does exactly that.
 *
 * 1. Finds (or creates once, keyed on `CYCLE_RESERVATION_MARKER`) one
 *    reservation on that property and re-points it at *yesterday → today*,
 *    `CONFIRMED`, with `cleaning_required: false`.
 *
 *    `cleaning_required: false` is the load-bearing detail: the checkout still
 *    transitions the flat, and the job reports it as `transitioned_without_task`
 *    (`docs/cleaning.md` §Operar el job), so `process_checkouts` does **not**
 *    auto-create a task. The spec then seeds its own with `createCleaningTask`
 *    (fixture 1.5), which is what task 3.1 asks for — and, because a reservation
 *    cannot carry two live cleanings (`uq_cleaning_tasks_live_reservation`),
 *    keeps a previous run's leftovers from deciding whether this run gets a task.
 *
 * 2. Runs the clock twice, because the three triggers cannot all be due at the
 *    same instant: `CHECKIN_TIME_REACHED` demands `checkin <= now < checkout`
 *    while `CHECKOUT_TIME_REACHED` demands `now >= checkout`
 *    (`PropertyStateMachine._validate_trigger_preconditions`). So the first run
 *    is frozen at midday *yesterday* (which is also what
 *    `CHECKIN_WINDOW_OPENED` needs — it requires the stay to start on the same
 *    calendar day as the instant, in the property's timezone) and the second
 *    runs on the live clock.
 *
 * The two clock times (`02:00` local check-in, `00:30` local check-out) are
 * chosen so the second run is due at *any* hour of the day: `00:30` local on a
 * `UTC+n` property is the previous day in UTC, so "now" is always past it.
 *
 * Idempotent: a property already in `AWAITING_CLEANING` is left alone.
 */
export async function ensurePropertyAwaitingCleaning(
  session: ApiSession,
  propertyId: string,
): Promise<void> {
  const initial = await propertyOperationalState(session, propertyId);
  if (initial === "AWAITING_CLEANING") {
    return;
  }
  if (!CYCLE_START_STATES.has(initial)) {
    throw new Error(
      `seed-context.ensurePropertyAwaitingCleaning: property ${propertyId} is in ${initial}; ` +
        `the cleaning cycle can only be driven from ${[...CYCLE_START_STATES].join("/")} or ` +
        "AWAITING_CLEANING. A previous run that died mid-cycle leaves the flat in a " +
        "CLEANING_* state — close or cancel its live cleaning task from /cleaning first.",
    );
  }

  const today = new Date();
  const checkOutDate = utcDate(today);
  const checkInDate = utcDate(new Date(today.getTime() - 24 * 60 * 60 * 1000));

  const onThisProperty = (await listReservations(session)).filter(
    (reservation) => reservation.property_id === propertyId,
  );
  const existing = onThisProperty.find(
    (reservation) => reservation.external_channel_id === CYCLE_RESERVATION_MARKER,
  );

  /*
   * The clock jobs refuse to guess between two stays covering the same night on
   * the same flat: `AdvancePropertyStatesUseCase` counts that as `ambiguous`,
   * writes nothing, and the chain below would then leave the flat exactly where
   * it found it. Checked here so that failure arrives named, with the offending
   * reservations, instead of as a silent no-op three calls later — and never
   * "fixed" by deleting a reservation this fixture did not create.
   */
  const overlapping = onThisProperty.filter(
    (reservation) =>
      reservation.id !== existing?.id &&
      LIVE_RESERVATION_STATUSES.has(reservation.status) &&
      reservation.check_in_date <= checkOutDate &&
      reservation.check_out_date >= checkInDate,
  );
  if (overlapping.length > 0) {
    throw new Error(
      `seed-context.ensurePropertyAwaitingCleaning: property ${propertyId} already has ` +
        `${overlapping.length} live reservation(s) overlapping ${checkInDate}..${checkOutDate} ` +
        `(${overlapping.map((r) => `${r.id} ${r.status} ${r.check_in_date}..${r.check_out_date}`).join("; ")}). ` +
        "The clock jobs report that as `ambiguous` and move nothing. Cancel or delete the extra " +
        "stay, or point the spec at a flat whose calendar is free for yesterday/today.",
    );
  }

  let reservationId: string;
  if (existing) {
    reservationId = existing.id;
  } else {
    const created = await fetch(`${BACKEND_URL}/api/v1/reservations`, {
      method: "POST",
      headers: authHeaders(session),
      body: JSON.stringify({
        property_id: propertyId,
        check_in_date: checkInDate,
        check_out_date: checkOutDate,
        external_channel_id: CYCLE_RESERVATION_MARKER,
        cleaning_required: false,
      }),
    });
    if (!created.ok) {
      throw new Error(
        `seed-context.ensurePropertyAwaitingCleaning: POST /api/v1/reservations -> ` +
          `${created.status} ${await created.text()}`,
      );
    }
    reservationId = ((await created.json()) as { id: string }).id;
  }

  // `POST` creates it `PENDING`; the clock triggers need `CONFIRMED`. Sent on
  // every run, not only on creation, so a reused reservation is re-pointed at
  // today's window.
  const patched = await fetch(`${BACKEND_URL}/api/v1/reservations/${reservationId}`, {
    method: "PATCH",
    headers: authHeaders(session),
    body: JSON.stringify({
      status: "CONFIRMED",
      cleaning_required: false,
      check_in_date: checkInDate,
      check_out_date: checkOutDate,
      check_in_time: "02:00:00",
      check_out_time: "00:30:00",
    }),
  });
  if (!patched.ok) {
    throw new Error(
      `seed-context.ensurePropertyAwaitingCleaning: PATCH /api/v1/reservations/${reservationId} -> ` +
        `${patched.status} ${await patched.text()}`,
    );
  }

  const { tenantId } = await apiMe(session);
  runSimAdvance(tenantId, `${checkInDate}T12:00:00+00:00`);
  runSimAdvance(tenantId);

  const reached = await propertyOperationalState(session, propertyId);
  if (reached !== "AWAITING_CLEANING") {
    throw new Error(
      `seed-context.ensurePropertyAwaitingCleaning: after the clock chain, property ${propertyId} ` +
        `is ${reached} and not AWAITING_CLEANING (it started at ${initial}). Check the ` +
        "`sim-advance` report for `blocked`/`ambiguous`/`not_eligible` — an overlapping stay on " +
        "the same flat is the usual cause.",
    );
  }
}
