# Suite E2E (Playwright)

## Purpose

Suite de pruebas end-to-end con `@playwright/test` que ejercita, contra el stack real levantado
por `make up` (nunca mocks), los tres flujos que `sdd/steering/testing.md` marca como críticos:
login, el ciclo de limpieza completo y el ciclo de incidencia. Es un proyecto separado del modo
browser de Vitest (`test:layout`) — navegación multi-página y multi-sesión, no una única
composición aislada — y corre tanto en local como en CI (`.github/workflows/e2e-tests.yml`).

## Requirements

### Infraestructura de la suite

- `frontend/playwright.config.ts` declara un único proyecto Chromium, `testDir: './e2e'`,
  `use: { baseURL: process.env.BASE_URL ?? 'http://localhost:3000' }` y `retries: 0`
  incondicional (nunca `CI ? 1 : 0`: un reintento gastaría del mismo presupuesto de
  login/refresh compartido por toda la suite — ver «Presupuesto de login/refresh» — sin
  mecanismo para contarlo).
- `globalSetup` (`frontend/e2e/global-setup.ts`) hace una petición HTTP directa a
  `${BACKEND_HEALTH_URL ?? 'http://localhost:8000/health'}` — el backend, **sin** pasar por el
  proxy same-origin del frontend, y **sin** el prefijo `/api/v1/`: `GET /health` está montado
  deliberadamente fuera de `API_V1_PREFIX` (`backend/app/main.py`), es el mismo endpoint que usa
  el healthcheck del contenedor. IF no responde, THEN THE SYSTEM SHALL abortar con un mensaje
  explícito en español ("stack no levantado — corre `make up` primero") antes de que corra
  cualquier spec, en vez de dejar que cada test falle por separado con un timeout de navegación
  genérico.
- `npx playwright test` (o `npm run test:e2e`) desde `frontend/` ejecuta este proyecto,
  independiente de `vitest.config.ts`/`test:layout`.
- WHEN el stack levantado usa `PORT_OFFSET` (worktree enlazado o CI, ver más abajo), THE SYSTEM
  SHALL permitir apuntar la suite al puerto desplazado con tres variables de entorno —
  `BASE_URL`, `BACKEND_HEALTH_URL`, `BACKEND_URL` — sin editar `playwright.config.ts` por
  worktree. `resolveBackendUrl()` (`frontend/e2e/fixtures/load-env.ts`) resuelve `BACKEND_URL`
  en este orden: valor explícito → derivado de `BACKEND_HEALTH_URL` quitando el `/health` final →
  default `http://localhost:8000`. Exportar solo `BACKEND_HEALTH_URL` basta para desplazar tanto
  el health-check como las llamadas de API de los fixtures.
- `frontend/e2e/fixtures/load-env.ts` (`loadRootEnv()`) parsea `.env` de la raíz del repo una vez
  y copia sus claves a `process.env` sin pisar las que ya estén puestas (para que un runner de CI
  que las exporte como variables reales no se vea afectado). Resuelve la ruta desde `__dirname`
  (no `import.meta.url`): `frontend/package.json` no declara `"type": "module"`, así que
  Playwright transpila specs/config a CJS, donde `import.meta.url` es un `SyntaxError` en tiempo
  de parseo — antes de que el try/catch del health-check llegue a ejecutarse.

### Fixtures compartidas

- `frontend/e2e/fixtures/auth.ts`: `type Role = "TENANT_OWNER" | "PROPERTY_MANAGER" | "CLEANER" |
  "TECHNICIAN"`; `credentialsFor(role)` lee las credenciales desde `.env` de la raíz
  (`BOOTSTRAP_OWNER_*`/`BOOTSTRAP_MANAGER_*` de `make bootstrap`, `SEED_CLEANER_*`/
  `SEED_TECHNICIAN_*` de `make seed-demo` — sin valores por defecto en el repo,
  `steering/security.md` regla 8); `loginAs(page, role)` hace login por clic (navegar a
  `/login`, rellenar `#email`/`#password`, enviar con `button[type="submit"]`) y espera el
  aterrizaje correcto: `TENANT_OWNER`/`PROPERTY_MANAGER` van directos a `/dashboard`;
  `CLEANER`/`TECHNICIAN` aterrizan primero en `/welcome?role=<role>` y `loginAs` hace clic en su
  único CTA (`/cleaner` o `/tech`) antes de esperar la ruta real del shell.
- `frontend/e2e/fixtures/seed-context.ts`: helpers de API autenticados para preparar el dato de
  partida de cada spec más allá de `make seed-demo` — `apiLogin`, `firstProperty`,
  `createCleaningTask`, `ensureUser`, `runSimAdvance` (dispara a mano `make sim-advance` en vez de
  esperar al scheduler real, vía `execFileSync`, con el `PORT_OFFSET` derivado del puerto de
  backend resuelto), `cancelLingeringIncidents`, `createUserWithTemporaryPassword`. Cada helper
  documenta el endpoint que usa.
- THE SYSTEM SHALL preparar el dato de partida de cada spec por API en su `test.beforeAll`/
  `beforeAll`, y ejercer el flujo bajo prueba por UI — nunca al revés: los specs no navegan para
  crear datos que ya cubren otros tests de integración/componente.

### Presupuesto de login/refresh (restricción de toda la suite)

- `RedisLoginThrottle` corta a partir de `login_rate_limit_per_minute` = **10** por IP en ventana
  fija de 60s, y `RefreshTokenUseCase` gasta del **mismo** contador — una navegación de Playwright
  cuenta como una unidad porque cada `page.goto` fuerza un refresh. Todas las navegaciones del
  navegador caen en la IP del contenedor `frontend` (proxy same-origin), una única clave
  compartida por **toda la corrida** de la suite, no solo por spec.
- WHEN una navegación agota el presupuesto, THE SYSTEM SHALL degradar de dos formas observadas:
  el login se rechaza (`loginAs` expira esperando el destino) o el login funciona pero la
  navegación siguiente rebota a `/login` (el token de sesión es válido; su refresh es el que
  falla) — el segundo caso no parece, a primera vista, un fallo de rate limit.
- `incident.spec.ts` mitiga esto con un contexto de navegador por rol, vivo durante todo el
  fichero y logueado una sola vez, y `visit()`/`loginOnce()` que esperan la ventana (65s) y
  reintentan una vez tras detectar el rebote (con un `BOUNCE_GRACE_MS` de 3s, porque el rebote es
  client-side y ocurre después de que el documento ya cargó). No se usa `storageState`: el
  refresh rota (`fam`), así que un estado capturado al loguear queda obsoleto en cuanto el
  contexto vivo refresca.
- Un cuarto spec, o `retries: 1` en CI, agotarían el presupuesto — es la razón de que `retries`
  esté fijado a `0` sin excepción.

### R2 — E2E: flujo de login

- `frontend/e2e/login.spec.ts`. WHEN se navega a `/login` con credenciales válidas de un usuario
  sembrado y se envía por clic, THE SYSTEM SHALL autenticar y redirigir a `/dashboard`.
- WHEN se introducen credenciales inválidas, THE SYSTEM SHALL mostrar el error (`<p role="alert">`)
  sin redirigir, sin asertar el texto i18n en sí.
- IF el usuario tiene `must_change_password` (creado vía `POST /api/v1/users`, contraseña
  temporal aleatoria por corrida — nunca un literal committeado, incidente de seguridad cerrado
  en `sdd/changes/archive/2026-09-*-hardening-release/tasks.md` «Review fix round 3»), THEN THE
  SYSTEM SHALL bloquear toda ruta autenticada salvo `me`/`logout`/`change-password` — verificado
  con `GET /api/v1/properties` devolviendo `{"error": {"code": "PASSWORD_CHANGE_REQUIRED"}}`, ya
  que el gate (`get_authenticated_request`) corre antes que el permiso propio de cualquier ruta.

### R3 — E2E: ciclo de limpieza

- `frontend/e2e/cleaning.spec.ts`. Precondición del ciclo entero: la propiedad tiene que estar en
  `AWAITING_CLEANING` — la única fila de `PropertyStateMachine._POLICY` que admite la primera
  asignación. Ninguna ruta HTTP escribe ese estado; `ensurePropertyAwaitingCleaning()` lo produce
  disparando a mano, con `runSimAdvance`, las dos corridas de reloj necesarias (`checkin`/
  `checkout` de una estancia ayer→hoy).
- WHEN el `PROPERTY_MANAGER` reasigna la tarea desde `/cleaning` antes de que se acepte, THE
  SYSTEM SHALL reflejar el nuevo asignado (leído del nodo de texto directo del `<span>` de valor,
  no con `toContainText` — `AssignCleanerControl` lista a todas las limpiadoras activas como
  `<option>` dentro del mismo elemento).
- WHEN el `CLEANER` acepta la tarea desde `/cleaner`, la abre en `/cleaner/tasks/[id]`, completa
  el checklist (18 ítems) y sube las fotos requeridas por categoría (6 categorías `required:
  true` — `_CHECKLIST_PHOTOS` en `backend/app/cli/seed_demo.py`, PNG real de 1×1 vía
  `setInputFiles`, porque el backend detecta el formato por bytes y no por `Content-Type`), THE
  SYSTEM SHALL marcar la tarea `COMPLETED`/`validation_status: PASSED` y devolver la propiedad a
  un estado del conjunto `{READY_FOR_NEXT_GUEST, AWAITING_CHECKIN, VACANT_READY}` (asertado por
  pertenencia, no literal — lo resuelve `ContextualStateResolver` según las reservas activas).
- El spec necesita una segunda limpiadora activa (`ensureUser`, email fijo
  `e2e-cleaner-relief@hardening-e2e.local`, idempotente) porque `AssignCleanerControl` no confirma
  una reasignación igual al asignado actual, y porque `process_checkouts` solo auto-asigna cuando
  el tenant tiene exactamente una limpiadora activa — un email aleatorio cambiaría en silencio ese
  comportamiento entre corridas.

### R4 — E2E: ciclo de incidencia

- `frontend/e2e/incident.spec.ts`. La incidencia se crea por el portal del huésped anónimo (`POST
  /api/v1/guest/incident/{token}`) — es la única fuente end-to-end conducible: `POST /incidents`
  no existe (asertado por diseño, `backend/app/maintenance/api/incidents_router.py`) y la fuente
  de la limpiadora acopla con una limpieza viva.
- La clasificación no es síncrona (regla 12(d) de `steering/security.md`: nada del escritor
  anónimo puede colgar del clasificador). WHEN un manager pulsa clasificar desde
  `/incidents/[id]` (`POST /incidents/{id}/classify`), THE SYSTEM SHALL invocar
  `RuleBasedIncidentClassifier`, verificado por la aparición de `ai_summary` (constante inglesa
  cerrada del adaptador, nunca i18n — regla 11 de `steering/security.md`) en la pantalla.
  `CRITICAL` se obtiene de forma determinista con vocabulario de la categoría `SAFETY` ("fuego",
  "humo", "gas", "alarma"); la incidencia recién creada trae `category: OTHER`/`severity: MEDIUM`
  por defecto, nunca `null`.
- WHEN la incidencia queda `CRITICAL`, THE SYSTEM SHALL pintar la propiedad en rojo
  (`PropertyStateBadge`, clase `bg-state-error/…`) mientras esté abierta; la clasificación y la
  aserción del badge pueden vivir en tests distintos del mismo `describe.serial`, con el estado
  llevado entre ellos por el orden garantizado de ejecución.
- WHEN el `TECHNICIAN` acepta y resuelve la incidencia desde `/tech/incidents/[id]` con coste
  final, THE SYSTEM SHALL cerrarla — salvo que `final_cost` supere `owner_approval_threshold_eur`
  del tenant (leído en vivo de `GET /api/v1/tenants/{id}`, nunca fijado en el spec), en cuyo caso
  IF el coste supera el umbral, THEN THE SYSTEM SHALL generar un `OwnerApproval` visible en
  `/approvals` para su respuesta — y el cierre deja `resolved_at: null` hasta que se aprueba.
  Aprobar el coste real no cierra la incidencia por sí solo: la devuelve a `IN_PROGRESS` con
  `approved_cost` fijado para que el técnico repita el cierre.
- `beforeAll` llama `cancelLingeringIncidents(session, SPEC_MARKER)` para cancelar solo las
  incidencias marcadas de corridas abortadas anteriores (nunca las del seed ni una real) —
  necesario porque `classify_incidents` (beat, cada 5 min) recoge cualquier `OPEN` sin
  `ai_classification`, incluida una `SAFETY` dejada viva por una corrida interrumpida, y dejaría
  la propiedad en rojo permanentemente.

### CI: workflow de tres jobs

- `.github/workflows/e2e-tests.yml` sigue el mismo patrón que `backend-tests.yml`/
  `frontend-tests.yml`: `e2e-tests-detect` (siempre corre, decide por diff sobre `backend/**`,
  `frontend/**`, `docker-compose.yml`, `Makefile`, `frontend/e2e/**` y el propio workflow),
  `e2e-tests-suite` (condicional), `e2e-tests` (consolidador `if: always()`, único contexto
  marcable). Sin `paths:` en `on:` — un filtro en el disparador dejaría el check sin reportar
  nunca en los PR que no lo tocan.
- `e2e-tests-suite` corre en `[self-hosted, dev]`, con Playwright en el **host** del runner (no
  en un contenedor): `make up`, espera de salud, `make bootstrap` + `make seed-demo`,
  `npm run test:e2e` desde `frontend/`, teardown en pasos `if: always()`.
- WHEN `e2e-tests-suite` levanta el stack, THE SYSTEM SHALL derivar `PORT_OFFSET = 10 × <i>` de
  `RUNNER_NAME` (patrón `autohostai-dev-vm-<i>`, `infra/environments/dev/RUNBOOK.md` §6.2) y
  pasarlo a `make up`/`make bootstrap`, fail-closed si `RUNNER_NAME` no encaja el patrón — sin
  desplazamiento, `make up` publica en `127.0.0.1:8000`/`127.0.0.1:3000`/`3000`, que
  `docker-compose.deploy.yml` mantiene ocupados de forma **permanente** en el mismo runner (app
  de dev desplegada, RUNBOOK §7.4), así que la colisión no era ocasional sino el 100% de las
  corridas.
- WHEN `e2e-tests-suite` opera Compose, THE SYSTEM SHALL fijar `COMPOSE_PROJECT_NAME:
  e2e-${{ github.run_id }}` a nivel de job, único por corrida, para que dos PRs concurrentes en
  agentes distintos del mismo runner no compartan (ni borren) volúmenes con nombre. El teardown
  final es `docker compose down --volumes --remove-orphans` (no `make down`, que deliberadamente
  no pasa `--volumes` porque en dev local esos volúmenes son la base de datos del desarrollador) —
  con `COMPOSE_PROJECT_NAME` único por corrida, sólo borra los volúmenes de esta corrida.
- WHEN se preparan credenciales de `bootstrap`/`seed-demo` para el job, THE SYSTEM SHALL
  generarlas con `openssl rand -hex 16` en el propio job (nunca un literal committeado en el
  YAML), escribirlas en un `.env` efímero antes de `make up` y borrarlo con `rm -f .env` en un
  paso `if: always()` **después** del teardown de Compose (antes rompería la interpolación de
  `${POSTGRES_DB:?…}` que la baja necesita).
- `scripts/check-detect-surface.py` añade un detector `e2e` (`e2e_surface()`, mismo mecanismo que
  `frontend_surface()`) que verifica que la superficie de `e2e-tests-detect` cubre lo que
  `e2e-tests-suite` ejecuta fuera de `backend/**`/`frontend/**` — hoy, `Makefile` por los
  `make <target>` de la suite. `scripts/test_detect_surface.py` lo cubre con sus propios casos.

### Exposición de red del stack de CI (riesgo aceptado)

- WHILE `e2e-tests-suite` corre, `backend`/`frontend` quedan publicados en todas las interfaces de
  una VM con IP pública (postura deliberada de `docker-compose.yml`, ver spec
  `local-environment`). **Se acepta**: la security list de OCI sólo permite el puerto 22 entrante
  (`infra/environments/dev/RUNBOOK.md`, ADR `0003-https-ingress-dev.md`); 8000/3000 no son
  alcanzables desde fuera de la VM. No hay mecanismo de bind-address override hoy (`PORT_OFFSET`
  desplaza el número de puerto y conserva la interfaz a propósito;
  `docker-compose.worktree.yml` retira los mapeos por completo, lo que dejaría a Playwright, que
  corre en el host, sin nada a lo que conectarse). Reabrir si la security list abre otro puerto
  entrante o el runner pasa a una red compartida.

## Auditoría DoD §28 (R5)

- `docs/dod-audit.md` documenta, ítem por ítem, el estado de los 20 puntos de PRD §28 con su
  evidencia. Resultado de esta auditoría (2026-09-13): **18/18** dominios de negocio bajo
  `backend/app/` (excluyendo `cli`/`core`/`provenance`/`scheduler`) tienen test de aislamiento de
  tenant — cero huecos, cero tests nuevos; y `PropertyStateMachine` tiene cobertura exhaustiva
  derivada de `_POLICY` — cero casos que añadir. Los huecos reales que la auditoría encontró
  (`#28.8`, `#28.17`, `#28.2`) son de **producto**, no de test, y quedan fuera de alcance de este
  change (ver `docs/dod-audit.md` para el detalle y por qué cada uno se deja abierto a propósito).
- `README.md` corrige la cifra de dominios (era 19 con un roster desactualizado; son 18) y enlaza
  `docs/dod-audit.md` desde una sección «Definition of Done del MVP».

## Key files

- `frontend/playwright.config.ts`, `frontend/e2e/global-setup.ts`.
- `frontend/e2e/fixtures/load-env.ts`, `fixtures/auth.ts`, `fixtures/seed-context.ts`.
- `frontend/e2e/login.spec.ts`, `cleaning.spec.ts`, `incident.spec.ts`.
- `.github/workflows/e2e-tests.yml`.
- `scripts/check-detect-surface.py` (`e2e_surface()`), `scripts/test_detect_surface.py`.
- `docs/dod-audit.md` — auditoría DoD §28 completa, incluidas las tablas de los 18 dominios y las
  transiciones de `PropertyStateMachine`.
- `.env.example` §«E2E test overrides» — `BASE_URL`/`BACKEND_HEALTH_URL`/`BACKEND_URL`.
