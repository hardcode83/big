# Tasks: hardening-release

<!-- Markers: "hard" en un encabezado de sección escala esa sección a Opus;
     "manual" en una línea de tarea marca lo que solo un humano o un entorno
     inalcanzable desde el worktree puede hacer. -->

## 1. Infraestructura E2E (Playwright) <!-- panel: PASS 2026-09-13 receipt:40b9b4c6 -->

- [x] 1.1 Añadir `@playwright/test` (misma major que la `playwright` ya fijada en `frontend/package.json`, `^1.62.1`) como devDependency; nuevo script `"test:e2e": "playwright test"`. [R1]
- [x] 1.2 `frontend/playwright.config.ts`: proyecto Chromium, `testDir: './e2e'`, `use: { baseURL: 'http://localhost:3000' }`, timeouts razonables para flujos multi-página. Distinto de `vitest.config.ts` — no toca ese fichero. [R1]
- [x] 1.3 `globalSetup` en `frontend/e2e/global-setup.ts`: petición HTTP a `http://localhost:8000/health` (backend directo, no vía proxy) antes de correr cualquier spec; si no responde, aborta con mensaje explícito ("stack no levantado — corre `make up` primero") en vez de dejar que cada test falle por timeout genérico. Referenciarlo desde `playwright.config.ts` (`globalSetup`). [R1.2]
- [x] 1.4 Fixture compartida `frontend/e2e/fixtures/auth.ts`: helper que hace login por clic (navegar a `/login`, rellenar credenciales, enviar, esperar `/dashboard`) parametrizado por rol — inspeccionar `frontend/features/auth/components/login-form.tsx` para los selectores reales, no inventarlos. Reutilizada por los tres specs de flujo. [R1]
- [x] 1.5 Fixture `frontend/e2e/fixtures/seed-context.ts`: helpers de API (autenticados) para crear por API el dato de partida que cada spec necesite más allá de `make seed-demo` (p. ej. una `CleaningTask`/incidencia en el estado exacto del test), documentando qué endpoint usa cada helper. [R1]

## 2. E2E: flujo de login [R2] <!-- panel: PASS 2026-09-13 receipt:fbb62c47 -->

- [x] 2.1 `frontend/e2e/login.spec.ts`: login válido → redirect a `/dashboard`; login inválido → error visible sin redirect; una petición autenticada representativa con un usuario `must_change_password` confirma el bloqueo `403 PASSWORD_CHANGE_REQUIRED` salvo `me`/`logout`/`change-password` (ver `docs/auth-account-recovery.md`). [R2]

## 3. E2E: ciclo de limpieza <!-- hard -->

- [ ] 3.1 `frontend/e2e/cleaning.spec.ts`: con una `CleaningTask` sembrada (fixture 1.5), el `PROPERTY_MANAGER` la reasigna desde `/cleaning` y el nuevo asignado se refleja. [R3.2]
- [ ] 3.2 Mismo spec: el rol `CLEANER` acepta la tarea desde `/cleaner`, abre `/cleaner/tasks/[id]`, completa el checklist y sube las fotos requeridas por categoría (ver `docs/cleaning.md`, `docs/cleaner-photo-requirements.md`); verificar que la tarea queda completada y que el estado operacional de la propiedad cambia según corresponda (`docs/dashboard.md`). [R3.1]

## 4. E2E: ciclo de incidencia <!-- hard -->

- [ ] 4.1 `frontend/e2e/incident.spec.ts`: crear una incidencia (por API o portal del huésped, según lo que el flujo real permita) y verificar que `MockAIAdapter` la clasifica; un manager la tría y asigna a un técnico desde `/incidents/[id]`. [R4.1]
- [ ] 4.2 Mismo spec: el técnico acepta y resuelve desde `/tech/incidents/[id]` con coste y materiales; verificar el cierre. Con severidad `CRITICAL`, verificar que la propiedad aparece en rojo en el dashboard mientras esté abierta. [R4.1, R4.2]
- [ ] 4.3 Mismo spec, variante con coste sobre el umbral del tenant: verificar que se genera un `OwnerApproval` visible en `/approvals` para su respuesta (`docs/maintenance.md`). [R4.3]

## 5. CI: workflow `e2e-tests` y detector

- [ ] 5.1 `.github/workflows/e2e-tests.yml`: patrón de 3 jobs (`e2e-tests-detect` / `e2e-tests-suite` / `e2e-tests` consolidador), copiando el fail-open/fail-closed y la superficie de detección de `frontend-tests.yml` (`backend/**`, `frontend/**`, `docker-compose.yml`, `Makefile`, `frontend/e2e/**`, este propio workflow). Runner `[self-hosted, dev]`, mismos SHA pineados que los otros workflows (`actions/checkout@11d5960a326750d5838078e36cf38b85af677262`, `actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020`, `astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9` si hace falta `uv` para el bootstrap del backend). [R1.3]
- [ ] 5.2 El job `e2e-tests-suite` hace `make up`, espera salud (reutilizar o adaptar el healthcheck de 1.3), `make bootstrap` + `make seed-demo`, corre `npm run test:e2e` desde `frontend/`, y `make down` en un paso `if: always()`. [R1.3]
- [ ] 5.3 Añadir un detector `e2e` a `scripts/check-detect-surface.py` (mismo mecanismo que `frontend_surface()`) que lea la superficie del `case` de `e2e-tests-detect` contra lo que `e2e-tests-suite` ejecuta; extender `scripts/test_detect_surface.py` con su caso. Correr `python3 scripts/check-detect-surface.py e2e` y confirmar que pasa. [R1.3]

## 6. Auditoría del DoD §28 <!-- hard -->

- [ ] 6.1 Enumerar los directorios de dominio de negocio bajo `backend/app/` (excluir `cli`, `core`, `provenance`, `scheduler`) y, para cada uno con estado propio scopado por tenant, confirmar en `backend/tests/<dominio>/` que existe un test de aislamiento tenant A / tenant B. Añadir el test que falte donde el hueco sea real. [R5.1]
- [ ] 6.2 Enumerar las transiciones (válidas e inválidas) de `PropertyStateMachine` (`backend/app/properties/domain/state_machine.py`) contra `backend/tests/properties/test_state_machine.py`; añadir el caso que falte. [R5.2]
- [ ] 6.3 `docs/dod-audit.md`: tabla de los 20 ítems de PRD §28 con su evidencia (test/archivo/comando); detalle de las tablas de 6.1 y 6.2. `#28.20` (un solo `make up` levanta todo) se documenta con la corrida de 7.3 como evidencia — ya construido por `local-environment`/`infra-scaffold`, no se reconstruye aquí. Corregir la cifra de dominios desactualizada en `README.md:311` (dice 19, con un roster que ya no incluye `statements` ni `audit`) contra el recuento real de 6.1. Enlazar `docs/dod-audit.md` desde `README.md`. [R5.3]

## 7. Verificación

- [ ] 7.1 Backend: `docker compose exec backend uv run pytest` — verde, incluyendo los tests nuevos de 6.1/6.2.
- [ ] 7.2 Frontend: `cd frontend && npm run typecheck && npm run lint && npm test` — verde.
- [ ] 7.3 E2E local: en este worktree, `make up PORT_OFFSET=<n>` (publica puertos — necesario porque Playwright corre en el host, no en la red de compose; ver `sdd/project.md` §Worktree bootstrap) y `cd frontend && BASE_URL=http://localhost:<3000+n> npm run test:e2e` (o el equivalente que 1.2 documente si `baseURL` se parametriza por variable de entorno) — los tres specs (2.1, 3.1-3.2, 4.1-4.3) en verde.
- [ ] 7.4 `python3 scripts/check-detect-surface.py e2e` (5.3) — verde.

## Implementation Notes

<!-- Append-only: cada implementador de sección añade aquí lo que la siguiente necesita. -->

### Section 1 (Infraestructura E2E)

- **Health-check endpoint discrepancy (D1 vs task 1.3):** `design.md` D1 says the `globalSetup`
  health check goes through the proxy at `/api/v1/health`. That endpoint does not exist —
  verified against `backend/app/main.py:392-397`: the real health route is `GET /health`,
  deliberately mounted OUTSIDE `API_V1_PREFIX` ("the container healthcheck in
  docker-compose.yml ... probes /health"). Followed task 1.3 instead: `frontend/e2e/global-setup.ts`
  hits `http://localhost:8000/health` directly (backend, no proxy). Override with
  `BACKEND_HEALTH_URL` env var for a `PORT_OFFSET` worktree (backend port shifts to `8000+n`).
- **`baseURL` override:** `playwright.config.ts` reads `process.env.BASE_URL` (default
  `http://localhost:3000`) so task 7.3's `BASE_URL=http://localhost:<3000+n> npm run test:e2e`
  works as documented, without editing the config per worktree.
- **Login selectors (`frontend/features/auth/components/login-form.tsx`) — no `data-testid`s
  exist on this form:** email input `#email`, password input `#password`, submit button
  `button[type="submit"]` (the label text is i18n and intentionally not used as a selector).
- **Post-login landing is role-dependent, not uniformly `/dashboard`** (task 1.4's text says
  "esperar /dashboard" for all roles — only true for two of the four):
  `TENANT_OWNER`/`PROPERTY_MANAGER` → `/dashboard` directly. `CLEANER`/`TECHNICIAN` → the login
  form redirects to `/welcome?role=<role>` first (`role-home.ts` + `app/(authenticated)/welcome/page.tsx`),
  which shows one CTA `<a href="/cleaner">` / `<a href="/tech">` the visitor must click — it does
  **not** auto-navigate. `fixtures/auth.ts`'s `loginAs(page, role)` handles this: it waits for
  `/welcome`, clicks the CTA (selected by `href`, not label text), then waits for the real shell
  route. Sections 2-4 should call `loginAs` rather than assume a single post-login URL.
- **Credentials come from the repo root `.env`, not hardcoded:** `BOOTSTRAP_OWNER_EMAIL/PASSWORD`,
  `BOOTSTRAP_MANAGER_EMAIL/PASSWORD` (from `make bootstrap`), `SEED_CLEANER_EMAIL/PASSWORD`,
  `SEED_TECHNICIAN_EMAIL/PASSWORD` (from `make seed-demo`) — steering/security.md #8 ships no
  defaults for these. `frontend/e2e/fixtures/load-env.ts` (`loadRootEnv()`) parses `.env` from
  the repo root once and copies keys into `process.env` without overwriting anything already
  set (so a CI runner that exports them as real env vars is unaffected); it's a small inline
  parser, not a new `dotenv` devDependency, since task 1.1 only asked for `@playwright/test`.
  Called from `global-setup.ts` (workers inherit `process.env` from the forked-after-setup
  process) and defensively again from `fixtures/auth.ts`/`fixtures/seed-context.ts`.
- **Reusable fixture API for sections 2-4:**
  - `fixtures/auth.ts`: `type Role = "TENANT_OWNER" | "PROPERTY_MANAGER" | "CLEANER" | "TECHNICIAN"`;
    `credentialsFor(role): { email, password }`; `loginAs(page, role): Promise<void>`.
  - `fixtures/seed-context.ts` (extend this file, don't fork a new one): `apiLogin(email, password): Promise<{ accessToken }>`
    (`POST /api/v1/auth/login`, hits the backend directly, no browser); `firstProperty(session): Promise<{ id, name }>`
    (`GET /api/v1/properties?page=1&per_page=1`); `createCleaningTask(session, { propertyId, reservationId?, scheduledStart?, scheduledEnd? })`
    (`POST /api/v1/cleaning-tasks`, `backend/app/cleaning/api/tasks_router.py` `create_cleaning_task`
    — the manual path alongside the automatic `process_checkouts`; caller needs a role `ManageDep`
    accepts, i.e. `TENANT_OWNER`/`PROPERTY_MANAGER` credentials). `BACKEND_URL` env override exists
    for `PORT_OFFSET` worktrees (default `http://localhost:8000`). No incident-seed helper yet —
    section 4's implementer should add it here with the same pattern (document the endpoint it calls).
- **Verification run:** `cd frontend && npm install` (host `node_modules` did not exist in this
  worktree — Docker volume-only, see `sdd/project.md` §Worktree bootstrap — installed here only
  for local verification), `npm run typecheck` (clean), `npm run lint` (clean),
  `npx playwright test --list` from an empty `e2e/` correctly reports "No tests found" / exit 1
  (Playwright's standard behavior for zero spec files, not a config error) — confirmed the config
  itself resolves correctly by temporarily dropping in a throwaway spec, which listed
  `[chromium] › _probe.spec.ts:2:5 › probe`, `Total: 1 test in 1 file`, exit 0, then removed it
  (no spec files belong to section 1).

### Section 1 — fix round 1

Three QA findings from the section 1 review, all fixed:

- **HIGH (`fixtures/load-env.ts:6`, R1.1) + HIGH (`global-setup.ts:3`, R1.2):** same root
  cause. `frontend/package.json` has no `"type": "module"`, so Playwright's TS loader
  transpiles specs/config to CJS, where `import.meta.url` (used to resolve the repo-root
  `.env` path) is a `SyntaxError` at parse time — before `global-setup.ts`'s health-check
  try/catch ever runs, so its intended clear message never surfaced. Fixed by resolving the
  path from `__dirname` instead: `@types/node` declares `__dirname` as a global regardless of
  `tsconfig.json`'s `module: esnext`, and it's populated for real once ts-node's CJS
  transpilation puts the file back in a CommonJS module scope. Removed the now-unused
  `node:url`/`fileURLToPath` import.
- **MEDIUM (`fixtures/seed-context.ts:71`, R1):** `firstProperty()` read `body.items`, but
  `GET /api/v1/properties` returns `PropertyPageResponse` (`backend/app/properties/api/schemas.py:391`),
  keyed `data`, not `items` — so the destructure always threw `undefined`. Changed both the cast
  (`{ items: SeedProperty[] }` → `{ data: SeedProperty[] }`) and the destructure
  (`body.items` → `body.data`).

Verification (this worktree, `cd frontend` first):
- `npm run typecheck` — clean, no errors.
- `npx playwright test` with zero spec files — `Error: No tests found` (expected: no specs
  exist yet for sections 2-4), no module-system error.
- Forced `global-setup.ts` to actually run (temporary throwaway spec, removed immediately
  after) with `BACKEND_HEALTH_URL=http://localhost:59999/health npx playwright test`: got the
  intended Spanish message — `E2E: no se pudo contactar con el backend en
  http://localhost:59999/health. Stack no levantado — corre \`make up\` primero (...). Causa:
  fetch failed` — thrown from `global-setup.ts:31`, confirming the ESM crash is gone and the
  real health-check failure path now surfaces as designed.
- `grep -n "body.items\|body.data" frontend/e2e/fixtures/seed-context.ts` — only `body.data`
  remains.

### Section 2 (E2E: flujo de login)

- **Stack left running for sections 3/4 to reuse:** this worktree had NO `.env` at all
  (`docker compose ps` failed with "Falta POSTGRES_DB en .env") — `make up PORT_OFFSET=77`
  created it from `.env.example` and generated `JWT_SECRET_KEY` as documented. Filled in the
  previously-empty secrets it needed to go further: `DEMO_ACCOUNT_PASSWORD`, the nine
  `BOOTSTRAP_*` vars, and `SEED_CLEANER_*`/`SEED_TECHNICIAN_*` (all local-only throwaway
  values, e.g. `owner@hardening-e2e.local` / `E2eOwnerPassw0rd!` — not secrets worth
  protecting, this is a local worktree stack). Ran `make bootstrap && make seed-demo`
  successfully after that. **Left running**: compose project `hardening-release`,
  `PORT_OFFSET=77` → postgres `5509`, redis `6456`, backend `8077`, frontend `3077`. Sections
  3/4 should reuse this (`BASE_URL=http://localhost:3077 BACKEND_HEALTH_URL=http://localhost:8077/health
  BACKEND_URL=http://localhost:8077 npx playwright test e2e/<spec>.ts` from `frontend/`) instead
  of running `make up`/`make bootstrap`/`make seed-demo` again — re-running `seed-demo` resets
  the demo tenant (see its own docstring: "lo aprovisiona si no existe y lo resetea si existe"),
  which would be harmless but unnecessary.
- **`must_change_password` user: created fresh via API per test run, not a static seeded
  account.** `POST /api/v1/users` (`CreateUserUseCase`) always sets `must_change_password: true`
  on a new user and returns its one-time temporary password in the response body — the cheapest
  realistic way to get one, and it does not clobber the `CLEANER`/`TECHNICIAN` credentials
  sections 3/4 depend on (resetting one of those via the CLI rescue command would have). Added
  `createUserWithTemporaryPassword(session, role)` to `fixtures/seed-context.ts`, following the
  file's existing pattern; email is randomised (`e2e-must-change-<ts>-<rand>@hardening-e2e.local`)
  so reruns never collide with a `409`.
- **`POST /api/v1/users` requires `MANAGE_USERS`, which is `TENANT_OWNER`-only.**
  `backend/app/auth/domain/policy.py`: `_USER_MANAGE` (`READ_USERS`+`MANAGE_USERS`) is folded into
  `ROLE_PERMISSIONS[TENANT_OWNER]` but not `PROPERTY_MANAGER`'s — confirmed by a live `403
  FORBIDDEN` when first tried with the manager's credentials. The login.spec.ts `must_change_password`
  test therefore calls `apiLogin`/`createUserWithTemporaryPassword` as `TENANT_OWNER`, not
  `PROPERTY_MANAGER`.
- **Representative non-exempt request used for the block assertion:** `GET /api/v1/properties`.
  The gate (`get_authenticated_request` in `backend/app/auth/api/dependencies.py`) runs before any
  route's own permission check, so it fires regardless of whether the `must_change_password` role
  would otherwise be allowed to call that route.
- **Error wire format confirmed:** `{"error": {"code": "PASSWORD_CHANGE_REQUIRED", ...}}`
  (`backend/app/core/errors.py`), not a flat `{"code": ...}`.
- **Post-login landing for this spec:** used `PROPERTY_MANAGER` throughout (both the valid-login
  test and the invalid-credentials test) rather than `TENANT_OWNER`/`CLEANER`/`TECHNICIAN` — it
  lands directly on `/dashboard` via `loginAs` (no `/welcome` detour), keeping the valid-login
  assertion simple. No new post-login-landing discoveries beyond what section 1 already documented
  above (`loginAs` handled the role-dependent landing correctly, unchanged).
- **Invalid-login test:** one deliberate bad password, no retry loop (steering/security.md #7
  rate-limit budget), asserted via `page.getByRole("alert")` (the form renders `<p role="alert">`)
  plus the URL still matching `/login` — no assertion on the i18n error text itself.
- **Verification run (this worktree, `cd frontend` first, stack at `PORT_OFFSET=77` above):**
  `npm run typecheck` — clean. `npm run lint` — clean. `npx playwright install chromium` (browser
  binary was missing in this worktree's Playwright cache). Then twice in a row:
  `BASE_URL=http://localhost:3077 BACKEND_HEALTH_URL=http://localhost:8077/health
  BACKEND_URL=http://localhost:8077 npx playwright test e2e/login.spec.ts` → `3 passed` both times
  (first run ~10.8s, second ~3.6s), confirming the randomised-email must_change_password user
  doesn't collide across reruns.

### Section 2 — fix round 1

QA HIGH finding (`fixtures/seed-context.ts:16` + `login.spec.ts:6`, referent R2.3): both files
defaulted `BACKEND_URL` to `http://localhost:8000` independently, unrelated to
`global-setup.ts`'s `BACKEND_HEALTH_URL`. Running the documented worktree command with only
`BACKEND_HEALTH_URL` set (as the section-2 notes above and task 7.3 imply is enough) correctly
pointed the health check at the shifted port but left every API call in `seed-context.ts` and
`login.spec.ts` hitting the unshifted `:8000` — a different, unrelated stack on this machine —
producing a misleading 401/403 instead of the intended assertion.

Fixed by adding `resolveBackendUrl()` to `frontend/e2e/fixtures/load-env.ts` (single shared
helper, not duplicated): explicit `BACKEND_URL` wins if set; otherwise it's derived from
`BACKEND_HEALTH_URL` by stripping a trailing `/health`; otherwise the `http://localhost:8000`
default. Both `fixtures/seed-context.ts` and `login.spec.ts` now call it instead of reading
`process.env.BACKEND_URL` directly.

Practical effect: exporting `BACKEND_HEALTH_URL` alone (already required for the health check)
is now sufficient — `BACKEND_URL` no longer needs to be set as a separate third var, though
setting it explicitly still works as an override (verified both ways below). Task 7.3's own
example command (line 46 above) only ever mentioned `BASE_URL`, never `BACKEND_HEALTH_URL`/
`BACKEND_URL`, so it didn't imply a third var and needed no change there. `global-setup.ts`'s
doc comment likewise only documents `BACKEND_HEALTH_URL` and didn't need updating. Left the
section-2 notes/verification-run text above as the historical record of that run (it exported
all three vars, which still worked and still passed); new runs only need `BACKEND_HEALTH_URL`.

Verification (this worktree, `cd frontend` first, stack at `PORT_OFFSET=77` still running from
section 2):
- `BASE_URL=http://localhost:3077 BACKEND_HEALTH_URL=http://localhost:8077/health npx
  playwright test e2e/login.spec.ts` (no `BACKEND_URL`) — `3 passed` (previously would have hit
  `:8000`).
- `BASE_URL=http://localhost:3077 BACKEND_HEALTH_URL=http://localhost:8077/health
  BACKEND_URL=http://localhost:8077 npx playwright test e2e/login.spec.ts` (explicit override) —
  `3 passed`.
- `npm run typecheck` — clean.
