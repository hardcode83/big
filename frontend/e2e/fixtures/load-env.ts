import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// frontend/e2e/fixtures/load-env.ts -> repo root is three levels up.
//
// Resolved from `__dirname`, not `import.meta.url`: Playwright's TS loader
// transpiles this file to CJS, where `import.meta` is a syntax error. `tsc`
// still type-checks it under `module: esnext` (per `frontend/tsconfig.json`),
// but `__dirname` is declared globally by `@types/node` regardless of the
// configured module kind, and is populated for real at runtime once ts-node's
// CJS transpilation puts this file back in a CommonJS module scope.
const ROOT_ENV_PATH = resolve(__dirname, "..", "..", "..", ".env");

let loaded = false;

/**
 * Parses the repo root `.env` (created by `make bootstrap` from
 * `.env.example`, never committed — `.gitignore` `.env*`) and copies any key
 * it finds into `process.env`, without overwriting a value already set there.
 *
 * The four demo-role credentials the E2E suite logs in with
 * (`BOOTSTRAP_OWNER_EMAIL/PASSWORD`, `BOOTSTRAP_MANAGER_EMAIL/PASSWORD`,
 * `SEED_CLEANER_EMAIL/PASSWORD`, `SEED_TECHNICIAN_EMAIL/PASSWORD`) live only
 * there — steering/security.md #8 ships no defaults for real user passwords —
 * and Playwright runs on the host, outside the `docker compose` env-file
 * wiring the backend container gets for free. This is a small inline parser
 * rather than a new `dotenv` devDependency, since task 1.1 only asks to add
 * `@playwright/test`.
 *
 * Idempotent, and silent when the file is missing (e.g. a CI runner that
 * exports these as real environment variables instead of writing `.env`).
 *
 * Called from `global-setup.ts` before any spec runs; Playwright workers are
 * forked after global setup completes, so they inherit the populated
 * `process.env`. `fixtures/auth.ts` and `fixtures/seed-context.ts` also call
 * it defensively in case a spec imports them outside a full `test:e2e` run.
 */
export function loadRootEnv(): void {
  if (loaded) {
    return;
  }
  loaded = true;

  let raw: string;
  try {
    raw = readFileSync(ROOT_ENV_PATH, "utf8");
  } catch {
    return;
  }

  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      continue;
    }
    const separator = trimmed.indexOf("=");
    if (separator === -1) {
      continue;
    }
    const key = trimmed.slice(0, separator).trim();
    let value = trimmed.slice(separator + 1).trim();
    const quoted =
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"));
    if (quoted) {
      value = value.slice(1, -1);
    }
    if (key && process.env[key] === undefined) {
      process.env[key] = value;
    }
  }
}
