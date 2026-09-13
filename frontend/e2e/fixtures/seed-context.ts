import { loadRootEnv } from "./load-env";

/**
 * API helpers for seeding data a spec needs *beyond* `make seed-demo` — e.g. a
 * `CleaningTask` in an exact starting state — so a test does not depend on
 * timing/ordering of the demo seed to find one. Calls the backend directly
 * (`BACKEND_URL`, default `http://localhost:8000`), never through the
 * frontend's same-origin proxy: these run from Node in the test process, not
 * from the browser page.
 *
 * Every helper documents the exact endpoint it calls, per task 1.5. Extend
 * this file (do not create a parallel one) as later sections need more seed
 * data — e.g. an incident helper for section 4.
 */

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

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
