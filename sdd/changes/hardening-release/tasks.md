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

## 3. E2E: ciclo de limpieza <!-- hard --> <!-- panel: PASS 2026-09-13 receipt:3faa8c50 -->

- [x] 3.1 `frontend/e2e/cleaning.spec.ts`: con una `CleaningTask` sembrada (fixture 1.5), el `PROPERTY_MANAGER` la reasigna desde `/cleaning` y el nuevo asignado se refleja. [R3.2]
- [x] 3.2 Mismo spec: el rol `CLEANER` acepta la tarea desde `/cleaner`, abre `/cleaner/tasks/[id]`, completa el checklist y sube las fotos requeridas por categoría (ver `docs/cleaning.md`, `docs/cleaner-photo-requirements.md`); verificar que la tarea queda completada y que el estado operacional de la propiedad cambia según corresponda (`docs/dashboard.md`). [R3.1]

## 4. E2E: ciclo de incidencia <!-- hard --> <!-- panel: PASS 2026-09-13 receipt:41ef4146 -->

- [x] 4.1 `frontend/e2e/incident.spec.ts`: crear una incidencia (por API o portal del huésped, según lo que el flujo real permita) y verificar que `RuleBasedIncidentClassifier` la clasifica; un manager la tría y asigna a un técnico desde `/incidents/[id]`. [R4.1]
- [x] 4.2 Mismo spec: el técnico acepta y resuelve desde `/tech/incidents/[id]` con coste y materiales; verificar el cierre. Con severidad `CRITICAL`, verificar que la propiedad aparece en rojo en el dashboard mientras esté abierta. [R4.1, R4.2]
- [x] 4.3 Mismo spec, variante con coste sobre el umbral del tenant: verificar que se genera un `OwnerApproval` visible en `/approvals` para su respuesta (`docs/maintenance.md`). [R4.3]

## 5. CI: workflow `e2e-tests` y detector <!-- panel: PASS 2026-09-13 receipt:7768f749 -->

- [x] 5.1 `.github/workflows/e2e-tests.yml`: patrón de 3 jobs (`e2e-tests-detect` / `e2e-tests-suite` / `e2e-tests` consolidador), copiando el fail-open/fail-closed y la superficie de detección de `frontend-tests.yml` (`backend/**`, `frontend/**`, `docker-compose.yml`, `Makefile`, `frontend/e2e/**`, este propio workflow). Runner `[self-hosted, dev]`, mismos SHA pineados que los otros workflows (`actions/checkout@11d5960a326750d5838078e36cf38b85af677262`, `actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020`, `astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9` si hace falta `uv` para el bootstrap del backend). [R1.3]
- [x] 5.2 El job `e2e-tests-suite` hace `make up`, espera salud (reutilizar o adaptar el healthcheck de 1.3), `make bootstrap` + `make seed-demo`, corre `npm run test:e2e` desde `frontend/`, y `make down` en un paso `if: always()`. [R1.3]
- [x] 5.3 Añadir un detector `e2e` a `scripts/check-detect-surface.py` (mismo mecanismo que `frontend_surface()`) que lea la superficie del `case` de `e2e-tests-detect` contra lo que `e2e-tests-suite` ejecuta; extender `scripts/test_detect_surface.py` con su caso. Correr `python3 scripts/check-detect-surface.py e2e` y confirmar que pasa. [R1.3]

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

### Section 3 (E2E: ciclo de limpieza)

- **`docs/cleaner-photo-requirements.md` (citado en la tarea 3.2) NO EXISTE.** No existe ni ha
  existido: el contrato real de las categorías de foto vive en `docs/cleaning.md` §«Las fotos de
  la limpieza» (qué pide la plantilla, `GET /photo-requirements`, `POST /photos`, y el orden de
  las tres cláusulas de `POST /complete`), y la vista de la limpiadora en `docs/cleaner.md`. Se
  siguió `docs/cleaning.md`. No es un blocker —el contrato está documentado, solo que en otro
  fichero— pero la referencia de tasks.md es falsa y no se corrige aquí porque tasks.md es el
  registro de lo que se pidió.
- **La precondición que manda sobre todo el ciclo: la vivienda tiene que estar en
  `AWAITING_CLEANING`.** `(AWAITING_CLEANING, CLEANER_ASSIGNED)` es la **única** fila de
  `PropertyStateMachine._POLICY` que admite ese disparador, así que sin ella la primera
  asignación responde `409 PROPERTY_STATE_CONFLICT` y el ciclo entero (aceptar → iniciar →
  cerrar) es inalcanzable. **Ninguna ruta HTTP escribe un estado operacional** — sólo los tres
  jobs de reloj—, y el seed deja las dos viviendas del tenant en `VACANT_READY` (PAJARITOS8) y
  `MAINTENANCE_REQUIRED` (REDES11, con estancia viva), ninguna en `AWAITING_CLEANING`.
- **Cómo se resuelve: `make sim-advance`, que es lo que `design.md` §Riesgos prescribe**
  («si un flujo depende de un job periódico, dispararlo a mano con los comandos ya existentes
  (`make sim-advance`, `make pms-sync`) en vez de esperar al scheduler real»). `runSimAdvance()`
  en `fixtures/seed-context.ts` lo ejecuta con `execFileSync`; es el único helper del fichero que
  no es una llamada HTTP, y está ahí a propósito (1.5 dice extender ese fichero, no forkear otro).
  `PORT_OFFSET` **se deriva del puerto del backend resuelto** (`8000+n` ⇒ offset `n`), no se lee
  del entorno: así el mismo `BACKEND_HEALTH_URL` que ya hace falta apunta también al overlay de
  compose correcto, sin una cuarta variable. Sin desplazamiento da `""`, que es lo que el Makefile
  trata como «sin offset».
- **Hacen falta DOS corridas del reloj, y las horas no son arbitrarias.** Los tres disparadores no
  pueden estar vencidos en el mismo instante: `CHECKIN_TIME_REACHED` exige `checkin <= now <
  checkout` y `CHECKOUT_TIME_REACHED` exige `now >= checkout`
  (`PropertyStateMachine._validate_trigger_preconditions`), y `CHECKIN_WINDOW_OPENED` exige además
  que la estancia **empiece el mismo día natural** que el instante, en la zona de la vivienda.
  `ensurePropertyAwaitingCleaning()` monta por eso una reserva *ayer → hoy* con `check_in_time`
  `02:00` y `check_out_time` `00:30` locales, y corre el reloj primero congelado en
  `ayer T12:00Z` y después con el reloj vivo. El `00:30` local es lo que hace que el segundo pase
  valga **a cualquier hora del día**: en una vivienda `UTC+n` ese instante cae el día anterior en
  UTC, así que `now` siempre lo ha pasado.
- **`cleaning_required: false` en esa reserva es un detalle que carga peso.** El checkout
  transiciona igual y el job lo cuenta como `transitioned_without_task` (`docs/cleaning.md`
  §Operar el job), así que `process_checkouts` **no** crea tarea: la crea el spec con
  `createCleaningTask` (fixture 1.5), que es lo que pide 3.1. Además evita el acoplamiento con
  `uq_cleaning_tasks_live_reservation` (una reserva no puede tener dos limpiezas vivas), que es lo
  que dejaría a una corrida sin tarea por culpa de restos de la anterior.
- **Y hace falta una SEGUNDA limpiadora**, porque `make seed-demo` sólo crea una y
  `AssignCleanerControl` no confirma una elección igual al asignado actual. `ensureUser()`
  (nuevo, idempotente, email fijo `e2e-cleaner-relief@hardening-e2e.local`) la crea una sola vez
  por tenant. **El email fijo no es cosmético**: el roster no es inerte — `process_checkouts` sólo
  auto-asigna cuando el tenant tiene *exactamente una* limpiadora activa (`docs/cleaning.md`
  §El ciclo) —, así que un email aleatorio por corrida iría cambiando en silencio cómo arranca
  cada corrida posterior. La seed es la **destinataria** de la reasignación, no el origen: es la
  única cuya contraseña conoce la suite (`SEED_CLEANER_*`), o sea la única que luego puede entrar
  y hacer 3.2.
- **Transición operacional real observada** (medida, no deducida):
  `VACANT_READY` →(reloj: checkin window / checkin / checkout)→ `AWAITING_CLEANING`
  →(`PATCH /cleaning-tasks/{id}` primera asignación)→ `CLEANING_SCHEDULED`
  →(`POST /start`)→ `CLEANING_IN_PROGRESS` →(`POST /complete`)→ **`VACANT_READY`**.
  El último salto es contextual: `_POLICY` admite `{READY_FOR_NEXT_GUEST, AWAITING_CHECKIN,
  VACANT_READY}` y lo resuelve `ContextualStateResolver` con las reservas que haya, así que el
  spec asserta **pertenencia al conjunto** y no un literal — que además son exactamente los tres
  estados 🟢 verdes de `docs/dashboard.md` §Colores de estado. Reapuntar una tarea ya `ASSIGNED`
  (la reasignación de 3.1) **no mueve la vivienda**, y el spec lo asserta.
- **Conjunto exacto de categorías de foto** (plantilla del seed, `_CHECKLIST_PHOTOS` en
  `backend/app/cli/seed_demo.py`), las **seis** `required: true`: `living_room`, `bedroom`,
  `bathroom`, `kitchen`, `entrance`, `damage_if_found`. El checklist son **18** ítems, todos
  `required: true` (`_CHECKLIST_ITEMS`). El spec no fija ninguno de los dos números: cuenta los
  `<li>` que la pantalla pinta y los recorre, así que una plantilla distinta no lo rompe.
- **Cómo se dan los bytes de la foto**: `setInputFiles({ name, mimeType, buffer })` con un PNG
  1×1 real de 70 bytes en base64 inline en el spec (`PIXEL_PNG`). Sin fichero binario en el repo
  —no había ninguno reutilizable— y sin ruta que el test pueda equivocar. Tiene que ser un PNG de
  verdad por dos razones: el backend decide el formato **por los bytes** y no por el
  `Content-Type` (`docs/cleaning.md` §Subir), y la galería lo pinta en un `<img>` cuyo
  `naturalWidth > 0` es la aserción que cierra el viaje completo (bytes guardados, firma válida,
  ruta sirviendo). El `<input type="file">` es `sr-only`/`aria-hidden` y `setInputFiles` lo
  maneja igual, que es justo para lo que existe.
- **Forma del ítem de checklist** (`GET /cleaning-tasks/{id}/checklist` → `{data: [...]}`):
  `{item_id, label, required, completed, completed_at, completed_by}`. Se marca con
  `POST /checklist/{item_id}/complete` (204, idempotente).
- **Selectores descubiertos — ninguno depende del idioma**, que es deliberado: `devices["Desktop
  Chrome"]` no fija locale y el idioma sale de i18next, así que atarse a un literal ES/EN sería
  frágil.
  - `/cleaning`: la fila es `li:has(h3#cleaning-task-<taskId>)`; el desplegable
    `select#assign-cleaner-<taskId>`; el botón de confirmar, su hermano adyacente
    (`#assign-cleaner-<taskId> + button`).
  - **Quién está asignado NO se puede leer con `toContainText`**: `CleaningTaskRow` pinta el
    nombre resuelto como un **nodo de texto pelado** dentro del `<span>` de valor del `Field`, y
    justo detrás `AssignCleanerControl` lista a **todas** las limpiadoras activas como `<option>`
    — así que el texto del `<span>` contiene los dos nombres esté asignado quien esté. El helper
    `assignedCleanerName()` lee sólo los nodos de texto directos. (Verificado con una mutación:
    quitando el clic de confirmar, la aserción falla con `Expected "E2E Cleaner" / Received
    "Relevo E2E"` — no es una aserción vacía.)
  - `/cleaner/tasks/[id]`: cada bloque por el id que declara su `aria-labelledby` —
    `section[aria-labelledby="cleaner-checklist-heading"]`, `...="cleaner-photo-reqs-heading"`,
    `...="cleaner-gallery-heading"`, `...="cleaner-action-bar-heading"` y, tras cerrar,
    `...="cleaner-completion-heading"` (el panel reversible, que es la forma que tiene la pantalla
    de decir que el cierre salió).
  - **La barra de acciones se navega por posición, no por etiqueta**: `CLEANER_ACTIONS`
    (`features/cleaner/lib/cleaner-actions.ts`) fija el orden en el DOM — `ASSIGNED` →
    [aceptar, rechazar], `ACCEPTED` → [iniciar], `IN_PROGRESS` → [cerrar] (+ el panel de
    incidencia, que se pinta *después* de la fila de botones). El primer botón es siempre el que
    avanza el ciclo, y el `toHaveCount` es lo que prueba en qué estado está la pantalla.
- **En qué estado queda todo al terminar el spec** (importante para la sección 4, que comparte
  stack y tenant): la vivienda elegida vuelve a **`VACANT_READY`**, su tarea queda `COMPLETED` con
  `validation_status: PASSED` (cerrar ya deja `PASSED` por sí solo), y la reserva marcada
  `external_channel_id = "e2e-cleaning-cycle"` se queda `CONFIRMED` con fechas ayer→hoy y
  `cleaning_required: false`. Cada corrida **reutiliza** esa reserva (no crea una nueva), que es
  lo que evita el fallo real medido aquí: dos estancias vivas solapadas en la misma vivienda hacen
  que los jobs de reloj respondan `ambiguous`, no escriban nada, y la cadena deje la vivienda donde
  estaba. `ensurePropertyAwaitingCleaning()` lo comprueba **antes** de correr el reloj y falla
  nombrando las reservas culpables, en vez de dejar un no-op silencioso — y nunca borra una reserva
  que no creó.
- **El spec elige vivienda por estado, no `firstProperty()`**: la primera cuyo
  `current_operational_state` esté en `AWAITING_CLEANING`/`VACANT_READY`/`READY_FOR_NEXT_GUEST`.
  Con el seed actual eso es siempre PAJARITOS8 (REDES11 está en `MAINTENANCE_REQUIRED` con
  estancia viva), pero la selección es por la precondición real y no por el orden del listado.
  Si la sección 4 deja una vivienda en `CRITICAL_INCIDENT`, este spec la salta sola.
- **Residuo conocido en el stack de este worktree**, de la exploración manual previa al spec, no
  del spec: una tarea `CREATED` sin asignar (`e9559b20…`, el reemplazo que crea todo `POST
  /cancel`), un usuario `CLEANER` `INACTIVE` (`e2e-cleaner-b@…`) y una reserva `CANCELLED`. Las
  tres son inertes para los specs (los localizadores van por `taskId`; una limpiadora inactiva no
  se ofrece como candidata; una reserva cancelada no cuenta para el reloj) y no se limpian porque
  cancelar una tarea `CREATED` sobre una vivienda ya en `AWAITING_CLEANING` sólo genera otro
  reemplazo — el bucle no converge.
- **Verificación (este worktree, stack `PORT_OFFSET=77` de la sección 2, sin `make up`/
  `bootstrap`/`seed-demo` de nuevo):** `npm run typecheck` y `npm run lint` limpios.
  `BASE_URL=http://localhost:3077 BACKEND_HEALTH_URL=http://localhost:8077/health npx playwright
  test e2e/cleaning.spec.ts` → **`2 passed`** tres veces seguidas (10.6 s / 9.7 s / 9.1 s),
  incluyendo una corrida que arrancó desde `VACANT_READY` y ejecutó la cadena completa de reloj y
  otra que arrancó ya en `AWAITING_CLEANING`. Suite E2E entera (`npx playwright test`, specs 2.1 +
  3.1-3.2) → **`5 passed`**, o sea que la sección 2 sigue verde. Comprobado además contra la API
  que la tarea del spec queda `COMPLETED`/`PASSED` y la vivienda en `VACANT_READY`.

### Section 4 (E2E: ciclo de incidencia)

- **La incidencia no la crea nadie por `POST /incidents`, porque esa ruta no existe.**
  `backend/app/maintenance/api/incidents_router.py` lo dice en su propio docstring («There is
  deliberately no `POST /incidents`»): cada fuente tiene dueño declarado. La única que un test
  puede conducir de punta a punta es el **portal del huésped**, `POST /api/v1/guest/incident/{token}`,
  **anónima** (el token del path es toda la credencial y tenant/vivienda/reserva salen de la sesión
  que resuelve el autorizador, nunca del cuerpo). La otra fuente viva es la de la limpiadora
  (`POST /cleaning-tasks/{id}/incidents`), descartada porque exige una limpieza viva y eso acopla
  la sección 4 con el dato de la sección 3.
- **La clasificación NO es síncrona, y eso es lo primero que había que medir.** Nada clasifica
  dentro de la petición que crea la incidencia, a propósito: su único escritor es una llamada
  anónima desde internet y colgar ahí el clasificador es lo que prohíbe la regla 12(d) de
  `steering/security.md` (`docs/maintenance.md` §El job de clasificación). Las dos vías son el job
  `classify_incidents` (beat, **cada 5 min**) y `POST /incidents/{id}/classify`. El spec usa la
  segunda, **pulsada desde la pantalla del manager**, así que 4.1 asserta producto y no scheduler.
  No hace falta `make sim-advance` en ningún punto de esta sección.
- **Cómo se consigue `CRITICAL` de forma determinista**: no es una elección manual del manager, es
  el veredicto del clasificador. `RuleBasedIncidentClassifier` mapea categoría → severidad
  (`_SEVERITIES`) y **`SAFETY` es la única categoría `CRITICAL`**. Sus palabras son
  `fuego, incendio, humo, gas, fire, smoke, alarm, alarma`. El spec reporta *«Olor a gas y humo en
  la cocina» / «Hay humo y huele a gas. La alarma no para de sonar.»* → **tres** aciertos, que dan
  `_STRONG_CONFIDENCE` **0.95**, por encima del `ai_confidence_threshold` **0.75** del tenant: con
  un solo acierto la confianza sería 0.80 (aún pasa) y con ninguno 0.30, que deja la incidencia
  `OPEN` para triaje humano. Para 4.3 se usa `APPLIANCE` (`nevera`, `horno`) → **`MEDIUM`**, que no
  mueve la vivienda; se evita a propósito cualquier palabra de agua (`agua`, `fuga`, `gotea`…),
  que la subiría a `HIGH`.
- **Una incidencia recién creada NO trae `category`/`severity` a `null`** — medido, y contradice lo
  que parecía razonable suponer: nace con los **defaults** de la entidad, `OTHER`/`MEDIUM` (que es
  lo que `docs/maintenance.md` dice de la ruta de la limpiadora: «La incidencia nace MEDIUM»). Lo
  que está vacío es `ai_summary`/`ai_classification`. El spec asserta los defaults, justamente para
  que el salto `MEDIUM` → `CRITICAL` de después signifique algo.
- **La prueba de que corrió el adaptador es `ai_summary`, y es la única cadena visible de la que el
  spec se cuelga**: `"Possible safety hazard reported at the property"`, constante de `_SUMMARIES`.
  **No es i18n** — sale del vocabulario cerrado en inglés que el adaptador declara y que
  `IncidentClassification` impone, precisamente para que no exista camino desde la prosa del huésped
  hasta esa columna (regla 11). Un badge de estado traducido habría probado sólo que *algo* cambió.
- **Umbral real del tenant: `owner_approval_threshold_eur = 100.00` EUR** (leído en vivo de
  `GET /api/v1/tenants/{tenant_id}` → `config`, que es el default de
  `backend/app/tenants/domain/entities.py`). Lo leen la propietaria **y** el manager; al técnico le
  responde **403**, que es exactamente por qué `docs/maintenance.md` dice que su pantalla «no
  calcula, no muestra y no anticipa» el umbral. El spec **lo lee, no lo fija**: 4.1/4.2 cierran con
  `45.50` (y trían con `umbral/2`), 4.3 cierra con `umbral + 150` = `250.00`. Las **dos** puertas
  existen y son distintas: la del triaje (`estimated_cost`, `related_type=INCIDENT`) y la del cierre
  (`final_cost`, `related_type=MAINTENANCE_COST`); 4.3 es la segunda, y por eso el triaje de 4.1 se
  queda deliberadamente por debajo.
- **La señal roja del dashboard, medida y no adivinada**: `PropertyCard` rotula cada tarjeta
  `aria-labelledby="property-card-<propertyId>"` y mete `PropertyStateBadge` en su `<header>`;
  `Badge` pinta un `<span data-slot="badge">`. El color sale de `TONE_BADGE_CLASS`
  (`lib/ui/status-tone.ts`) y el tono `red` lo tiene **sólo** `CRITICAL_INCIDENT`
  (`components/property-state-badge.tsx`), que es también la fila 🔴 de `docs/dashboard.md`
  §Colores de estado. La clase concreta observada en el navegador es
  `bg-state-error/15 text-state-error-text border-state-error/40` (etiqueta «Incidencia crítica»),
  y el spec asserta `/bg-state-error\//`. **No existe `data-testid` en esa tarjeta.**
- **Por qué el spec corre sobre REDES11 y no sobre la vivienda de la sección 3.**
  `propertyForIncidentCycle()` elige la primera vivienda cuyo estado **no** esté en el conjunto del
  que la sección 3 elige (`AWAITING_CLEANING`/`VACANT_READY`/`READY_FOR_NEXT_GUEST`). Con el seed
  eso es REDES11, y el detalle que lo hace **auto-restaurable** es que REDES11 arrastra una
  incidencia `HIGH` abierta del seed: `ContextualStateResolver.after_incident_resolution` recalcula
  desde las incidencias todavía activas —`CRITICAL` → `CRITICAL_INCIDENT`, si no `HIGH` →
  `MAINTENANCE_REQUIRED`, si no contextual—, así que el ciclo completo es
  `MAINTENANCE_REQUIRED` →(clasificar `CRITICAL`)→ `CRITICAL_INCIDENT` →(resolver)→
  **`MAINTENANCE_REQUIRED`**. El spec captura ese estado como *baseline* en `beforeAll` y asserta el
  regreso, en vez de fijar un literal.
- **Trampa real: una incidencia que el spec deje viva NO es inerte.** `classify_incidents` recoge
  todo lo `OPEN` sin `ai_classification` cada 5 minutos, así que el reporte deliberadamente `SAFETY`
  de una corrida abortada lo clasifica el scheduler minutos después, deja la vivienda en
  `CRITICAL_INCIDENT` **para siempre** (nadie la va a cerrar) y la corrida siguiente captura ese
  estado como su baseline. Medido: dos corridas abortadas dejaron exactamente eso y la vivienda se
  quedó roja. Por eso `beforeAll` llama a `cancelLingeringIncidents(session, SPEC_MARKER)`, que
  cancela sólo lo que lleva el marcador `[e2e-incident-spec` en el título — nunca las del seed,
  nunca una real.
- **El presupuesto de login del backend es de toda la suite E2E, y es el hallazgo con más alcance de
  esta sección** (afecta a la sección 5, CI, y a la 7.3):
  - `RedisLoginThrottle` cuenta en `login:ip:<ip>` y corta a partir de
    `login_rate_limit_per_minute` = **10**, en ventana **fija** de 60 s (`EXPIRE … NX`, no desliza).
  - **`RefreshTokenUseCase` gasta del MISMO contador**, a propósito y razonado en el código («The
    SAME bucket as login on purpose… splitting it would let a caller spend two budgets»). Su
    estimación de coste —«a legitimate refresh is a few per hour»— vale para una persona navegando
    una SPA; **no vale para Playwright**, donde cada `page.goto` es una carga completa que tira el
    access token de memoria y obliga a refrescar. **Una navegación, una unidad de las diez.**
  - Y todas caen en **una sola clave**: `login:ip:172.20.0.7`, la IP del **contenedor de frontend**
    (el navegador habla con Next.js y Next.js proxea al backend). Observado a 9/10 con 40 s de TTL.
    Las llamadas de Node contra `BACKEND_URL` llegan desde el host (`192.168.65.1`) y gastan otro
    contador — por eso los helpers de `seed-context.ts` son gratis y los pasos de navegador no.
  - Se confirmó en los logs del backend: `Login rate limit exceeded for ip=172.20.0.7` → `429` en
    `/auth/login`, y `Refresh rate limit exceeded for ip=172.20.0.7` → `429` en `/auth/refresh`.
  - **Dos síntomas, y sólo el primero parece un fallo de login**: (1) el login se rechaza y
    `loginAs` expira esperando la URL de destino; (2) **el login funciona y la navegación
    *siguiente* rebota a `/login`** — la sesión es buena, su refresh es el rechazado. El (2) se
    presenta como una aserción fallando contra la pantalla de login, sin nada que apunte a un rate
    limit: la primera versión de este spec lo reportó como «la barra de acciones del manager tiene
    0 botones».
  - Mitigación, toda dentro de `incident.spec.ts`: **un contexto de navegador por rol, vivo durante
    todo el fichero y logueado una sola vez** (tres logins para tres tests), y `visit()`/`loginOnce()`,
    que esperan a que la ventana caduque (65 s) y reintentan **una** vez. No se snapshotea
    `storageState`: el refresh **rota** (el claim `fam` es una familia de tokens), así que un estado
    capturado al loguear queda obsoleto en cuanto el contexto vivo refresca, y restaurarlo aterriza
    en `/login` — probado. El rebote hay que detectarlo **después** de `goto` (es client-side: el
    documento carga en la ruta pedida y sólo al contestar el `429` enruta a `/login`), de ahí el
    `BOUNCE_GRACE_MS` de 3 s.
  - **Lo que esto significa para la sección 5**: una pasada completa de la suite cabe, pero **va al
    filo**. Si se añade un cuarto spec, o si CI reintenta (`retries: 1`), hay que contar
    navegaciones, no sólo logins. Las secciones 2 y 3 **no** tienen esta recuperación; hoy pasan
    porque corren antes y el presupuesto aún no está agotado.
- **Selectores descubiertos (ninguno depende del idioma, misma disciplina que la sección 3):**
  - `/incidents/[id]`: la barra del manager es
    `article[aria-labelledby="incident-heading"] section` filtrado por *tiene `button`* — es la
    única `<section>` del detalle con botones (las demás son `<dl>` de sólo lectura) y las hojas
    Radix se portalan a `document.body`, así que no entran. El orden es fijo
    (`MANAGER_ACTIONS[status]` en `features/incidents/lib/manager-actions.ts`): `OPEN` →
    [classify, triage, cancel]; `CLASSIFIED` → [assign, triage, cancel]. **`nth(0)` es siempre
    «avanzar el ciclo»**, igual que la convención que documentó la sección 3 para la limpiadora.
  - **El botón de confirmar de una hoja/diálogo se localiza por `button[aria-busy]`**: tanto
    `AssignSheet` como `TriageSheet` pintan exactamente un control con
    `aria-busy={mutation.isPending}` (React lo serializa como `aria-busy="false"` en reposo) y el
    aspa de cerrar no lo lleva. Los `id` de sus campos vienen de `useId()` y **no** sirven como
    selector; dentro del diálogo se va por `select` (asignar) e `input[type="number"]` (triaje).
  - `/tech/incidents/[id]`: `page.locator("main button")` — el shell del técnico
    (`TechnicianShell`) pinta un `<main>` que deja fuera la topbar. Orden fijo por `TECH_ACTIONS`
    (`features/tech/lib/tech-actions.ts`): `ASSIGNED` → [accept, reject], `ACCEPTED` →
    [en-route, reject], `IN_PROGRESS` → [wait-parts] **más el formulario de cierre**. El
    `toHaveCount(2)` es lo que prueba en qué estado está la pantalla.
  - **El formulario de cierre sí trae `id` estables**, los únicos de esta sección:
    `#tech-final-cost` y `#tech-materials`, con `form:has(#tech-final-cost) button[type="submit"]`.
  - `/approvals`: la cola es una `<table>`; la fila se localiza por el **título de la incidencia**,
    que `RequestCell` pinta tal cual y que es cadena **propia del spec** (con `RUN_TAG` único), no
    traducida. Dentro de la fila, los botones son **aprobar y luego rechazar**, en ese orden, y sólo
    se pintan con `RESPOND_OWNER_APPROVALS` — verificado por API que el manager recibe **403** al
    responder, aunque sí puede **leer** la cola.
  - `GET /incidents` y `GET /owner-approvals` devuelven envelope **`items`**, no el `data` de
    propiedades/usuarios/reservas. Cuesta un `undefined` silencioso si se asume mal.
- **Hechos de producto que el spec asserta y conviene no reaprender**: aprobar el coste real **no
  cierra** la incidencia — la devuelve a `IN_PROGRESS` con `approved_cost` fijado y el técnico
  repite el cierre, para que `resolved_at` siga significando «lo dio por terminado»; y el cierre por
  encima del umbral escribe `final_cost` pero deja `resolved_at` a `null`.
- **Residuo conocido en el stack de este worktree, y el hecho de producto que lo explica**: queda
  **una `OwnerApproval` `PENDING` huérfana** (`0b511362…`, 250.00 EUR, incidencia
  `7b566b60… "(e2e 1789322804666)"`). Salió de limpiar a mano las incidencias que dejaron las
  corridas abortadas *antes* de que existiera el marcador `SPEC_MARKER`. El hecho: **cancelar una
  incidencia que está en `AWAITING_OWNER_APPROVAL` no cierra su aprobación**, y después ya no hay
  forma de cerrarla — responderla da `409 "Incident is already CANCELLED and admits no further
  transition"`. Es inerte para el spec (4.3 localiza su fila por el título con `RUN_TAG` único, y
  las tres corridas verdes de abajo se hicieron con esa fila ya presente), pero se deja anotado
  porque a) ensucia `/approvals` y b) es una asimetría real del dominio, no un accidente del test.
- **En qué estado queda el stack**: vivienda PAJARITOS8 en `VACANT_READY` y REDES11 en
  `MAINTENANCE_REQUIRED` (ambas como las dejó el seed / la sección 3); las tres incidencias del seed
  intactas (`ASSIGNED HIGH`, `CLASSIFIED MEDIUM`, `CLASSIFIED LOW`); ninguna incidencia del spec
  viva; la aprobación huérfana de arriba. El spec añade además una reserva reutilizable en REDES11
  marcada `external_channel_id = "e2e-incident-cycle"`, `CONFIRMED`, con ventana **a 30 días vista**
  y re-apuntada en cada corrida: futura a propósito, porque la ventana del portal es sólo cota
  **superior** (`now <= check_out + grace_days`, sin cota inferior), así que autoriza siempre, y
  porque estando lejos de *hoy* ningún job de reloj la ve elegible ni puede convertirse en la
  segunda estancia solapada que haría que `sim-advance` reportara `ambiguous` a la sección 3.
- **Verificación (este worktree, stack `PORT_OFFSET=77` de la sección 2, sin `make up`/`bootstrap`/
  `seed-demo`):** `npm run typecheck` y `npm run lint` limpios.
  `BASE_URL=http://localhost:3077 BACKEND_HEALTH_URL=http://localhost:8077/health npx playwright
  test e2e/incident.spec.ts` → **`3 passed`** en **tres corridas seguidas** (27.2 s / 1.5 m / 2.0 m —
  las dos últimas más lentas porque agotan el presupuesto de login y la recuperación espera la
  ventana a propósito). Suite completa
  `npx playwright test e2e/login.spec.ts e2e/cleaning.spec.ts e2e/incident.spec.ts` → **`8 passed`**
  (2.3 m), o sea que las secciones 2 y 3 siguen verdes y no hay contaminación cruzada.
  **Prueba de mutación**: quitando el clic de clasificar en 4.1, el spec falla en
  `expect(page.getByText(SAFETY_AI_SUMMARY)).toBeVisible()` — «element(s) not found» —, así que la
  aserción que sostiene «RuleBasedIncidentClassifier la clasifica» no es vacía. (Los fallos reales de las primeras
  corridas sirvieron de mutación natural para otras dos: el badge rojo resolvió al `<span>` real con
  su clase `bg-state-error/…`, y `toHaveCount(3)` de la barra del manager dio 0 cuando la página no
  era la esperada.)

### Section 5 (CI: workflow `e2e-tests` y detector)

- **`setup-uv`/`setup-python` NO hacían falta, y no se añadieron.** Confirmado leyendo
  `backend-tests.yml` y el Makefile: `make up` levanta postgres/redis/backend/worker/beat/frontend
  enteros dentro de Docker (`docker compose up -d --build`), y `make bootstrap`/`make seed-demo`
  son `docker compose exec backend python -m app.cli.*` — todo el lado backend vive en el
  contenedor, con su propio `uv`/Python ya resuelto por `backend/devops/Dockerfile`. El único
  proceso que corre en el runner (fuera de Docker) es Playwright (design D1/D2), que solo necesita
  Node — de ahí que `e2e-tests-suite` solo traiga `actions/setup-node` (mismo SHA/versión que
  `frontend-tests.yml`) y `python3` del propio runner para `check-detect-surface.py` en el job
  `-detect` (stdlib, sin `uv`, como los otros tres detectores).

- **`timeout-minutes: 25` en `e2e-tests-suite`**, no los 15 de `frontend-tests.yml` (que no arranca
  ningún stack) ni un valor menor: el suelo real es `make up` (build + migraciones + arranque de
  los 6 servicios, ~1-2 min en frío), más `npm ci`/instalación de Chromium en el host, más la suite
  misma (medida en 7.3: ~2.3-3 min, hasta ~2 min más si el limitador de login 10/min/IP —contador
  COMPARTIDO por todo el run, steering/security.md #7— fuerza una recuperación dentro de un spec,
  ya manejada por los specs). 25 min deja margen holgado sobre ese peor caso sin ser tan generoso
  como para ocultar un cuelgue real.

- **Credenciales de bootstrap/seed: generadas en el propio job, nunca en `.env.example`.**
  `make bootstrap`/`make seed-demo` exigen `BOOTSTRAP_*`/`SEED_*` (nueve + seis variables,
  `backend/app/cli/bootstrap.py`/`seed_demo.py`) y `.env.example` las deja vacías a propósito
  (steering/security.md #8) — `make up` solo genera `JWT_SECRET_KEY`/`ENCRYPTION_KEY`, nunca estas.
  Un nuevo paso (`Preparar .env con credenciales efímeras de bootstrap/seed`) las escribe en el
  `.env` del runner ANTES de `make up` (tienen que existir cuando el contenedor `backend` se crea,
  porque las recibe vía `env_file` una sola vez al arrancar), con valores desechables que solo
  viven durante esta ejecución — ninguno es un secreto real, mismo criterio que el
  `openssl rand -hex 32` que `backend-tests.yml` genera para su propio JWT. `frontend/e2e/fixtures/
  load-env.ts` (task 1.1) lee ese mismo `.env` para que Playwright, en el host, inicie sesión con
  las mismas cuentas — no hace falta exportarlas aparte como variables de entorno del job.

- **Desviación estructural: un paso `docker compose down --volumes --remove-orphans || true` ANTES
  de `make up`**, que ni el proposal ni el design piden explícitamente. Motivo: los volúmenes con
  nombre de `make up` (`postgres_data`, entre otros) persisten en este runner *persistente* entre
  ejecuciones del mismo workflow — a diferencia de los `services:` efímeros de
  `backend-tests.yml` — y `make down` (el paso `if: always()` que el task 5.2 sí pide, sin tocar el
  Makefile) para y borra contenedores pero NUNCA volúmenes. `make bootstrap` es convergente
  (`apply_plan`, docstring de `bootstrap.py`: "a second run leaves the state the configuration
  declares"), pero `seed_demo.py` documenta que su dataset de negocio (reservas, `CleaningTask`) NO
  tiene esa garantía — así que cada corrida parte de volúmenes limpios en vez de confiar en una
  idempotencia que el propio comando no promete. No se tocó el Makefile (fuera del área de
  cambios de esta sección): la limpieza vive solo en el workflow nuevo, con `docker compose`
  invocado directamente (equivalente a `$(COMPOSE)` sin overlay, porque el runner no es un
  worktree enlazado — design D2).

- **`e2e_surface()` en `scripts/check-detect-surface.py`**: mismo mecanismo que `frontend_surface()`
  (mismos helpers `_job_lines`/`_run_texts`/`_root_script_refs`/`_MAKE_TARGET`), apuntado al job
  `e2e-tests-suite` de `e2e-tests.yml` en vez de `frontend-tests-suite`. La superficie real de hoy
  es exactamente `{"Makefile"}` (los cuatro `make <target>` de la suite; los pasos `npm`/
  `playwright install` corren bajo `working-directory: frontend`, ya anclados por `frontend/*`,
  igual que los pasos npm de `frontend_surface()`). Añadido a `WORKFLOWS` en el CLI y a `DETECTORS`
  en `scripts/test_detect_surface.py`, con dos pruebas nuevas paralelas a las de frontend
  (`test_e2e_surface_end_to_end_resolves_makefile_and_fails_closed` sintetiza un workflow con un
  guard `scripts/` sin anclar para probar el fail-closed; `test_e2e_surface_matches_todays_real_workflow`
  fija la superficie real de hoy) y extensión de `test_gate_altering_inputs_do_not_skip` con las
  anclas de `e2e` (backend/**, frontend/**, docker-compose.yml, Makefile disparan; README.md no
  sobre-dispara).

- **Verificación**: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/e2e-tests.yml'))"`
  → válido (PyYAML 6.0.3 disponible en este host). `python3 scripts/check-detect-surface.py e2e` →
  `OK`. Los otros tres detectores (`rule11`, `compose`, `frontend`) siguen en `OK` sin cambios de
  comportamiento. `pytest scripts/test_detect_surface.py -q` (comando real del repo para este
  fichero — no hay `pytest.ini`/`pyproject.toml` en la raíz, así que es el `pytest` del PATH del
  host, 7.3.1) → **23 passed** (18 preexistentes + 5 nuevas), ninguna marcada `xfail`/`skip`.
  No se ejecutó el workflow en GitHub Actions real (no se puede desde este worktree); la
  verificación de que la suite E2E en sí pasa contra un stack real es la de 7.3 (sección 1-4, ya
  verde), no de esta sección — 5.1-5.3 son la superficie de CI, no una corrida nueva del stack.

### Section 5 — fix round 1

- **Hallazgo (revisión de seguridad, MEDIUM):** el paso "Preparar .env con credenciales
  efímeras de bootstrap/seed" de `.github/workflows/e2e-tests.yml` escribía las cinco
  contraseñas `BOOTSTRAP_*_PASSWORD`/`SEED_*_PASSWORD` como literales fijos en el YAML
  (`CiE2eOwnerPassw0rd!`, etc.) — el mismo valor en cada ejecución de CI, a diferencia de
  `JWT_SECRET_KEY`/`ENCRYPTION_KEY` (mismo fichero y `backend-tests.yml`), generados por
  `openssl rand` en cada corrida. Incumplía steering/security.md regla 8 (cero secretos reales
  en repo) porque, aunque el `.env` en sí es efímero, el valor commiteado en el workflow es
  permanente y público en el historial: cualquiera con acceso de lectura conoce de antemano la
  contraseña real de las cuentas OWNER/MANAGER/SUPER_ADMIN/CLEANER/TECHNICIAN del stack
  efímero mientras esté vivo.
- **Cambio:** cada uno de los cinco `set_var *_PASSWORD` ahora pasa `"$(openssl rand -hex 16)"`
  en vez del literal — 32 caracteres hexadecimales generados en el momento, uno distinto por
  variable y por corrida, mismo patrón que `JWT_SECRET_KEY=$(openssl rand -hex 32)` de
  `backend-tests.yml`. Los emails/nombres (`owner@ci-e2e.test`, "CI E2E Owner", etc.) se dejan
  como literales fijos: no son secretos y ayudan a depurar una corrida fallida.
  Verificado contra `backend/app/auth/domain/password_policy.py`: la política real exige
  `PASSWORD_MIN_LENGTH = 12` y `PASSWORD_MAX_BYTES = 72`, sin regla de clase de carácter — 32
  hex chars (32 bytes) cumple ambos límites con margen.
- **Verificación:** `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/e2e-tests.yml'))"`
  → válido. `python3 scripts/check-detect-surface.py e2e` → `OK` (sin cambios, esta sección no
  toca el detector). Grep de las cinco cadenas literales originales
  (`CiE2eOwnerPassw0rd!`, `CiE2eManagerPassw0rd!`, `CiE2eSuperAdminPassw0rd!`,
  `CiE2eCleanerPassw0rd!`, `CiE2eTechnicianPassw0rd!`) contra el fichero final → ninguna
  coincidencia.
