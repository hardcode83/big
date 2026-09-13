import type { FullConfig } from "@playwright/test";

import { loadRootEnv } from "./fixtures/load-env";

/**
 * Direct backend health check (task 1.3), NOT via the same-origin proxy.
 *
 * `design.md` D1 says this should hit `/api/v1/health` through the frontend
 * proxy; `tasks.md` 1.3 (written after D1, more specific) says to hit the
 * backend directly at `http://localhost:8000/health`. Verified against
 * `backend/app/main.py:395` — the real health endpoint is `GET /health`,
 * deliberately NOT under `API_V1_PREFIX` ("the container healthcheck in
 * docker-compose.yml ... probes /health"), so `/api/v1/health` does not
 * exist. Following the task: the more specific, and the only one that
 * actually resolves.
 *
 * `BACKEND_HEALTH_URL` overrides the default for an SDD worktree, where
 * `make up PORT_OFFSET=<n>` shifts the published backend port to `8000+n`.
 */
const BACKEND_HEALTH_URL =
  process.env.BACKEND_HEALTH_URL ?? "http://localhost:8000/health";

export default async function globalSetup(_config: FullConfig): Promise<void> {
  loadRootEnv();

  let response: Response;
  try {
    response = await fetch(BACKEND_HEALTH_URL, { method: "GET" });
  } catch (cause) {
    const reason = cause instanceof Error ? cause.message : String(cause);
    throw new Error(
      `E2E: no se pudo contactar con el backend en ${BACKEND_HEALTH_URL}. ` +
        "Stack no levantado — corre `make up` primero (o `make up PORT_OFFSET=<n>` " +
        "en un worktree, y exporta BACKEND_HEALTH_URL con el puerto desplazado). " +
        `Causa: ${reason}`,
    );
  }

  if (!response.ok) {
    throw new Error(
      `E2E: el backend respondió ${response.status} en ${BACKEND_HEALTH_URL}. ` +
        "Stack no levantado correctamente — corre `make up` primero.",
    );
  }
}
