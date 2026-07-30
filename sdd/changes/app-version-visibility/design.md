# Design: app-version-visibility

## Context

El CD (`.github/workflows/deploy-dev.yml`) construye las dos imágenes `prod` arm64 y las etiqueta `sha-<commit>` + `dev`; el job `deploy` escribe `IMAGE_TAG=sha-${GITHUB_SHA}` en el `.env` de la VM y `docker-compose.deploy.yml` pinea los servicios con `${IMAGE_TAG}`. Ninguna de las dos imágenes lleva identidad dentro: los Dockerfiles no declaran `ARG` de build metadata (salvo `NEXT_PUBLIC_APP_ENV` en el `builder` del frontend) ni emiten labels OCI.

En el backend, `backend/app/main.py` expone `create_app()` con `API_V1_PREFIX = "/api/v1"`, monta un único router (`auth_router`) y registra `/health` **inline dentro de la factoría**, fuera del prefijo (decisión D2 de `auth-tenancy`). `backend/app/core/config.py` instancia `settings = Settings()` en tiempo de import, con `extra="ignore"`, `jwt_secret_key` requerido (`Field(min_length=32)`) y el resto de campos con default. `backend/tests/test_route_authorization.py` exige que toda ruta declare autorización salvo las 7 de `ANONYMOUS_ENDPOINTS`, keyeadas por `(método, path)`.

En el frontend, `frontend/lib/config/` es la única frontera de configuración: `public.ts` construye `PublicRuntimeConfig` desde una allowlist explícita (hoy `appEnv`, `defaultLocale`, `featureFlags`), `server.ts` es `server-only` y expone `backendInternalUrl`, y `runtime-config-provider.tsx` lo entrega al cliente. `app/layout.tsx` llama a `buildPublicRuntimeConfig()` y lo pasa por `AppProviders`. El chrome del shell son Server Components que resuelven texto con `getServerT`; `ShellFrame` (`features/shell/components/shell-frame.tsx`) recibe slots `skipLink`/`topbar`/`sidebar`/`bottomNavigation` y **no tiene slot de footer**. `lib/api/client.ts` es un transporte genérico **sin un solo call site**: no existe ninguna integración frontend→backend.

## Decisions

### D1 — `VERSION` en la raíz como única fuente de verdad de la base

**Chosen:** un fichero `VERSION` en la raíz del repo con la versión base en una línea (`0.1.0`). El CD lo lee (`$(cat VERSION)`) para componer la cadena. La versión del *producto* es un hecho de producto, no de componente: ninguno de los dos manifiestos es naturalmente canónico, y hoy ambos declaran `0.1.0` de forma independiente sin que nadie los use.

La comprobación de paridad es un **target de Makefile (`make version-check`) invocado desde el gate de CI**, no un test de pytest. Motivo empírico, verificado durante `/sdd:run`: el contenedor de backend monta solo `./backend:/app`, así que un test en `backend/tests/` **no puede ver** `VERSION` ni `frontend/package.json` cuando se ejecuta con el comando que `project.md` manda usar (`docker compose exec backend uv run pytest`) — `ls /VERSION` dentro del contenedor da `No such file or directory`. Un test así pasaría en CI (donde el runner tiene el repo completo) y sería inejecutable en el flujo de desarrollo documentado. El target de Makefile corre en el host, donde los tres ficheros existen, y el gate lo invoca; una sola implementación, verificable en los dos sitios.

**Consecuencia asumida:** el step ensancha la responsabilidad del gate más allá del backend, y el Purpose de `specs/backend-ci.md` la acota hoy a *"la suite completa del backend"*. Se acepta por pragmatismo —`backend-tests` es el **único** workflow que corre en cada PR sin filtro de `paths`, y la §Estado de esa misma spec constata que "el frontend tiene sus propios comandos de verificación que ningún workflow ejecuta todavía"—, y por eso `specs/backend-ci.md` entra en "Affected specs" del proposal: al archivar hay que documentar ahí que el gate también valida la paridad de versión entre los dos componentes.

Rejected: test de pytest en `backend/tests/` — inejecutable en el contenedor, por lo de arriba. Rejected: un `skipif` cuando los ficheros no se ven — un test que se salta en el flujo normal no es un gate. Rejected: workflow propio `version-parity.yml` — más limpio conceptualmente, pero duplica checkout y arranque de runner para tres líneas de shell. *(El motivo **no** es evitar un required check: la §Estado de `specs/backend-ci.md` documenta que hoy ningún check puede marcarse obligatorio en este repo — plan privado sin protección de rama, `403: Upgrade to GitHub Pro` —, así que ese coste no existe. Corregido tras el hallazgo del panel de CI/CD.)* Rejected: `pyproject.toml` como canónico — obliga al frontend a parsear TOML para un dato que no es del backend. Rejected: derivar los manifiestos del `VERSION` en build — dos generadores por un string; validar es más simple que generar.

### D2 — La procedencia se calcula una vez en el CD y viaja como build-args

**Chosen:** un job/step previo compone el bloque en un solo sitio y lo expone por `$GITHUB_OUTPUT`; los dos builds lo consumen como build-args. Garantiza R1.5 (misma cadena en ambas imágenes) por construcción en vez de por disciplina, y deja el cálculo del PR en un único lugar auditable.

Rejected: calcularlo dentro de cada job de build — dos implementaciones del mismo string, que es exactamente cómo se desincronizan. Rejected: calcularlo en el job `deploy` — llega tarde: la identidad tiene que estar *dentro* de la imagen (R1.3).

### D3 — El número de PR sale del subject del merge commit, con degradación explícita

**Chosen:** `git log -1 --format=%s` sobre el checkout (depth 1 basta: `github.sha` para un `push` es el propio merge commit) y extracción de `#(\d+)`. Sin llamadas a la API y sin `pull-requests: read`. Si no hay coincidencia, el campo queda vacío y la UI dice "push directo".

Rejected: `gh api /repos/{repo}/commits/{sha}/pulls` — correcto con cualquier estrategia de merge, pero añade permiso, red y un modo de fallo al build por un dato que el commit ya lleva encima. Queda documentado como plan B si el repo pasa a rebase (R6.5).

### D4 — Backend: la procedencia entra por `Settings` con defaults, y la ruta vive en `create_app()`

**Chosen:** cuatro campos nuevos en `Settings` (`app_version`, `build_commit`, `build_pr`, `built_at`, `build_run_id`, `build_ref`), **todos con default vacío/`None`**, y `@app.get("/version")` registrado inline en `create_app()` junto a `/health`. Dos razones duras: `settings = Settings()` corre en tiempo de import, así que un campo requerido convertiría cualquier imagen sin build-args en un `ValidationError` al arrancar — la versión nunca puede impedir el arranque; y `pydantic-settings` es case-insensitive, así que el `ENV APP_VERSION` de la imagen mapea directo sin código de pegamento.

Rejected: leer `os.environ` en el router — rompe la norma de que la configuración vive en `core/config.py`. Rejected: crear un dominio `backend/app/version/` con las cuatro capas `domain/application/infrastructure/api/` — `backend-architecture.md` reserva esa estructura para dominios de negocio y su propia sección "cuándo simplificar" avisa contra la ceremonia sin invariante que proteger; `/version` no tiene entidad, ni persistencia, ni regla. `/health` ya sentó el precedente exacto. Rejected: montarlo bajo `/api/v1/` — versiona el *build*, no la *API*; misma lógica que D2 de `auth-tenancy`.

### D5 — `("GET", "/version")` se añade a `ANONYMOUS_ENDPOINTS`, y nada más

**Chosen:** una línea en `backend/tests/test_route_authorization.py`. Es el mecanismo que ese test diseñó a propósito ("getting past it requires adding the path to the list below, which is a visible diff"), y el keyeo por `(método, path)` mantiene el resto acotado: un `POST /version` futuro seguiría en rojo.

Rejected: darle un `Permission` y hacerla autenticada — el enum solo tiene permisos self-service (`READ_OWN_PROFILE`, `MANAGE_OWN_SESSION`) y ampliar el modelo de autorización por una ruta de diagnóstico es coste sin beneficio. Rejected: exceptuar por prefijo o por path sin verbo — reintroduce la vacuidad que ese test documenta haber cerrado.

### D6 — Frontend: la cadena de versión entra en `PublicRuntimeConfig`; la URL del repo **no**

**Chosen:** `PublicRuntimeConfig` gana `appVersion` y `buildCommitShort` — con eso el badge compone `0.1.0+a2f3c1d` (OQ2) sin necesitar nada más, y la fecha de build no llega al snapshot público porque solo la usa el panel. La URL del repositorio, el número de PR y el `run_id` se quedan en `server.ts` (`getServerConfig()`) y solo llegan al HTML de la superficie de operación, ya convertidos en `href` por un Server Component. Así la decisión de divulgación queda **estructural**: lo que no está en la allowlist no puede aparecer en el bundle del login por descuido.

Rejected: meter todo en `PublicRuntimeConfig` — el snapshot lo recibe *toda* la app, incluido `/login` y `/guest/[token]`, lo que contradice R3.6 y R4.3. Rejected: que el panel lea `process.env` — prohibido fuera de `lib/config` por la spec de `frontend-foundation`.

### D7 — El badge es un slot `footer` nuevo en `ShellFrame`

**Chosen:** `ShellFrame` gana un slot `footer` opcional, y cada shell decide si lo pasa. Server Component puro, cero JS de cliente, una sola posición para las cinco superficies. El `main` mueve su `pb-16 md:pb-0` al contenedor para que en móvil el footer quede **por encima** del `BottomNavigation`, que es `fixed inset-x-0 bottom-0 z-40 md:hidden`.

Rejected: el slot `end` del `Topbar` — habría que reescribirlo en cada shell (su default es `<LocaleSwitcher />`) y compite por un `h-14` que en móvil ya va justo. Rejected: renderizarlo en cada página — 21 sitios donde olvidarlo.

### D8 — El panel de procedencia es un client island que recibe props ya resueltas

**Chosen:** un Server Component del shell de workspace construye el objeto (cadena, commit corto y completo, PR, fecha, `run_id`) con los enlaces ya formados y lo pasa como props a un island `"use client"` que usa el `Sheet`/`Dialog` de Radix ya presente en `components/ui/`. Mismo patrón que `SkipLink` (recibe `label`) y `Sidebar` (recibe `profile`): la interactividad es de cliente, la resolución de datos es de servidor.

Rejected: un client component que lea la configuración por `useRuntimeConfig()` — obligaría a meter la URL del repo en el snapshot público, que es lo que D6 evita.

### D9 — La deriva se comprueba **fuera de la ruta de render**, desde el propio panel

**Chosen:** el panel, al abrirse, pide la versión del backend a un Route Handler del frontend (`app/deployment/version/route.ts`) que lee `BACKEND_INTERNAL_URL` en servidor y consulta `/version` con un timeout corto; si difieren, el panel lo dice. El badge no depende de nada de esto.

Es lo que **preserva literalmente** la spec viva de `frontend-foundation`, que exige mantener `BACKEND_INTERNAL_URL` *"server-only and unread at shell render"* y renderizar el shell completo sin backend. Leerlo en el render del layout cumpliría el espíritu (con timeout y degradación) pero cambiaría la letra de una cláusula que existe justo para esa garantía, y metería una llamada HTTP en el camino de render de cada entrada al workspace.

El path **no va bajo `/api/`** a propósito: la entrada `api-ingress-routing` del roadmap se inclina por un `rewrite` de Next para `/api/*` hacia el backend, y un Route Handler ahí colisionaría. El handler devuelve **solo cadenas de versión** — ni PR, ni URL de repo, ni `run_id` — porque el túnel lo haría alcanzable públicamente (R5.6/R3.6).

Rejected: leer el backend en el render del `(workspace)/layout.tsx` con memo por proceso — más automático (la deriva salta sin abrir nada) y casi gratis tras la primera llamada, pero enmienda la cláusula de la spec y acopla el render al backend. Es la **OQ1**. Rejected: consultar `/version` desde el navegador contra el backend — exigiría exponerlo por el túnel y CORS.

### D10 — Sin migraciones, sin modelos, sin dependencias nuevas

**Chosen:** la identidad vive en la imagen. No hay tabla, ni modelo, ni revisión de Alembic, ni paquete nuevo en `pyproject.toml`/`package.json`. El gate `backend-tests` (que corre `alembic upgrade head`, `alembic check`, la suite y `alembic downgrade base` **sin filtro de paths**) queda intacto por construcción.

Rejected: registrar cada despliegue en una tabla — es historial de despliegues, explícitamente fuera de alcance; Actions y GHCR ya lo tienen.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Fuente de verdad | `VERSION` *(nuevo)* | Base de versión en una línea (D1) |
| CD | `.github/workflows/deploy-dev.yml` | Step que compone la procedencia y la publica por `$GITHUB_OUTPUT` (D2, D3); los dos builds la pasan como `build-args` y como `labels` OCI |
| Imagen backend | `backend/devops/Dockerfile` | `ARG`+`ENV` de los seis campos al final de la etapa `prod` |
| Imagen frontend | `frontend/devops/Dockerfile` | `ARG`+`ENV` `NEXT_PUBLIC_*` en la etapa `builder`, junto a `NEXT_PUBLIC_APP_ENV` |
| Backend config | `backend/app/core/config.py` | Seis campos nuevos en `Settings`, todos con default (D4) |
| Backend ruta | `backend/app/main.py` | `@app.get("/version")` inline en `create_app()` (D4) |
| Backend tests | `backend/tests/test_route_authorization.py` | `("GET", "/version")` en `ANONYMOUS_ENDPOINTS` (D5) |
| Backend tests | `backend/tests/test_version.py` *(nuevo)* | Contrato de `/version`, forma de `test_health.py`; caso de campos ausentes |
| Backend tests | `backend/tests/test_config.py` | Los campos nuevos no rompen el arranque cuando faltan |
| CI de versión | `Makefile` (target `version-check`), `.github/workflows/backend-tests.yml` (step que lo invoca) | `VERSION` == `pyproject.toml` == `package.json`, comprobado en el host porque el contenedor de backend no ve esos ficheros (D1, R6.2) |
| Config frontend | `frontend/lib/config/public.ts` | `appVersion` y `buildCommitShort` en la allowlist (D6) |
| Config frontend | `frontend/lib/config/server.ts` | URL de repo, PR y `run_id` como valores server-only (D6) |
| Shell | `frontend/features/shell/components/shell-frame.tsx` | Slot `footer` + reubicación del `pb-16` (D7) |
| Shell | `frontend/features/shell/components/version-badge.tsx` *(nuevo)* | Badge sobre el `Badge` de `components/ui/` |
| Shell | `frontend/features/shell/components/provenance-panel.tsx` *(nuevo)* | Island `"use client"` con `Sheet` (D8) |
| Shell | `workspace-shell.tsx`, `public-shell.tsx`, `cleaner-shell.tsx`, `technician-shell.tsx` | Pasan el slot `footer`; solo workspace pasa además el panel |
| Shell | `guest-shell.tsx` | **Sin cambios** — el portal de huésped no lleva badge (R3.7) |
| Shell | `frontend/features/shell/index.ts` | Exporta lo nuevo si `app/` lo necesita |
| Route Handler | `frontend/app/deployment/version/route.ts` *(nuevo)* | Lee `BACKEND_INTERNAL_URL`, consulta `/version` con timeout, devuelve solo cadenas (D9) |
| i18n | `frontend/locales/{es,en}/common.json` | Claves del badge y del panel |
| Compose dev | `docker-compose.yml` | `NEXT_PUBLIC_BUILD_*` explícitas en el servicio `frontend` (no tiene `env_file`) |
| Docs | `infra/environments/dev/RUNBOOK.md` §6.4 y §7 | Confirmar rollback con el badge; descartar caché del edge |
| Docs | `docs/app-version-visibility.md` *(nuevo)*, `README.md` | Capacidad y flujo, incluidas las tres trampas de R6.4/R6.5 |

## Data & interfaces

**`GET /version` (backend, sin autenticación, fuera de `/api/v1`)**

```jsonc
{
  "version": "0.1.0+2026-07-30.a2f3c1d",  // cadena canónica, con fecha (OQ2)
  "commit": "a2f3c1d…",        // SHA completo, o null si no se horneó
  "pr": 42,                     // o null → "push directo"
  "built_at": "2026-07-30T09:14:02Z",
  "run_id": "1234567890",
  "ref": "main"
}
```

**snake_case**, no camelCase: es la convención de la API existente (`access_token`, `token_type`, `expires_in` en `TokenPairResponse`) y de PRD §23. Un campo no horneado se serializa como `null`, no como `""`, para que el consumidor distinga "no hay dato" de "el dato es cadena vacía".

**`GET /deployment/version` (frontend, Route Handler)** — devuelve `{"frontend": "<cadena>", "backend": "<cadena>|null"}`. Nada más: sin PR, sin URL de repo, sin `run_id`.

**Variables de entorno** — ninguna nueva en runtime de producción (D10): la identidad se hornea. En dev local se declaran explícitamente en `docker-compose.yml` y degradan a local/desconocido.

En el **backend**, un solo grupo, `ENV` en la etapa `prod`: `APP_VERSION`, `BUILD_COMMIT`, `BUILD_PR`, `BUILT_AT`, `BUILD_RUN_ID`, `BUILD_REF`.

En el **frontend hay dos clases**, y la distinción es la que hace cumplible D6 sin romper R1.3 (precisión añadida al implementar la sección 3):

| Clase | Variables | Dónde acaba | Por qué |
|---|---|---|---|
| `NEXT_PUBLIC_*` (build-arg en `builder`) | `NEXT_PUBLIC_APP_VERSION`, `NEXT_PUBLIC_BUILD_COMMIT_SHORT` | **Inlineadas en el bundle** → llegan al navegador en todas las superficies | Es lo que pinta el badge, y solo un valor dentro del bundle detecta que el edge sirve JS viejo. Son las dos únicas que D6 admite en el snapshot público |
| `ENV` planas (etapa `prod`) | `BUILD_COMMIT` (completo), `BUILD_PR`, `BUILT_AT`, `BUILD_RUN_ID`, `BUILD_REF`, `REPO_URL` | Horneadas en la imagen pero **solo legibles por el servidor de Next** (`lib/config/server.ts`) | Alimentan el panel de procedencia. Horneadas (R1.3 se cumple: no son config de compose) pero **fuera del bundle**, así que no llegan al login ni al portal de huésped (D6, R3.6, R4.3) |

Marcar una de las de la segunda clase como `NEXT_PUBLIC_*` sería un fallo de divulgación silencioso: pasaría los tests y metería el número de PR y la URL del repo en el bundle público.

**Labels OCI** en ambas imágenes: `org.opencontainers.image.source`, `.revision`, `.version`, `.created`.

**Esquema de base de datos**: sin cambios. **Migraciones**: ninguna.

## Risks & mitigations

| Riesgo | Mitigación |
|---|---|
| La suite se cae al añadir una ruta anónima | Es determinista y conocido: D5 lo resuelve con una línea, y el gate `backend-tests` lo detecta en el PR (corre sin filtro de paths) |
| Un campo requerido en `Settings` impide arrancar una imagen sin build-args | D4: todos con default. Test explícito en `test_config.py` |
| El pareo con el PR se rompe en silencio si el repo pasa a rebase | Documentado en R6.5 con el plan B (`gh api …/pulls`); el modo de fallo visible es "push directo" en la UI |
| Colisión del Route Handler con el `rewrite` de `api-ingress-routing` | D9: el path no va bajo `/api/` |
| El handler del frontend queda público por el túnel | D9: devuelve solo cadenas de versión, nunca PR ni URL de repo |
| Cachéo del edge sirviendo un bundle viejo con versión vieja | Es la funcionalidad, no el riesgo: exactamente lo que hace visible |
| La versión en pantalla parece atrasada respecto a `main` | R6.4: el filtro de paths del CD hace que sea el último commit que **disparó build**; se documenta |
| Divulgación sin sesión por `/version` | Decidido y aceptado (repo privado, entorno dev). El alcance exacto, corregido tras el hallazgo del panel de seguridad: un llamante anónimo obtiene cadena de versión, **SHA completo de 40 caracteres**, número de PR, fecha de build, `run_id` de Actions y `ref` — no el SHA corto, como decía antes esta fila. Lo que **no** sale es la URL del repositorio ni el título del PR (R2.5), y tampoco entran en el snapshot público del frontend (D6). Hoy `/version` solo es alcanzable por túnel SSH o desde la red del compose: el túnel enruta únicamente `http://frontend:3000` con catch-all 404 |

## Open questions

Ninguna abierta. Las dos que había se cerraron con el usuario el 2026-07-30, antes de `/sdd:tasks`:

**OQ1 (cerrada) — La deriva se comprueba solo al abrir el panel.** Confirmada la elección de D9: la cláusula de `frontend-foundation` que exige `BACKEND_INTERNAL_URL` *server-only y no leído en el render del shell* **queda intacta**, y el badge no hace ninguna llamada de red nunca. Se descartó leerlo en el render de `(workspace)/layout.tsx` con memo por proceso: habría hecho que la deriva salte sin abrir nada, pero al precio de enmendar la spec viva y acoplar el render al backend. Consecuencia para `/sdd:tasks`: R5.3 (aviso de deriva) se satisface **dentro del panel**, no como banner global.

**OQ2 (cerrada) — El badge muestra `<base>+<sha-corto>`; la fecha de build va en el panel.** Es decir `0.1.0+a2f3c1d` en pantalla, y `commit` completo, `PR`, `builtAt` y `run_id` en el panel. Motivo: ~24 caracteres con la fecha completa compiten por el espacio de un móvil, y `steering/frontend.md` es mobile-first. Consecuencia: la cadena **canónica** (la de `/version`, los labels OCI y `docker inspect`) mantiene la fecha —`0.1.0+2026-07-30.a2f3c1d`— y lo que se acorta es solo su **presentación** en el badge; el panel muestra los dos datos por separado, así que no se pierde nada.
