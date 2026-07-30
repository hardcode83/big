# Proposal: app-version-visibility

## Why

Hoy **no hay forma de saber qué está desplegado sin entrar en la VM**. La única identidad que existe es el tag de imagen (`sha-<commit>` inmutable, más el móvil `dev`), y el CD la escribe en el `.env` de la máquina; para leerla hay que abrir un túnel SSH y hacer `grep IMAGE_TAG .env` o `docker compose images`. El repo no tiene git tags (`git tag` devuelve 0), no hay SemVer ni CHANGELOG, y el `version = "0.1.0"` de `backend/pyproject.toml` y `frontend/package.json` es **metadato muerto**: nunca se incrementa, nunca se hornea en la imagen y nunca se expone. Las imágenes tampoco llevan labels OCI, así que `docker inspect` no ayuda.

Eso encarece dos operaciones concretas que ya están documentadas como manuales. El **rollback es por SHA** (`RUNBOOK §6.4`, re-lanzar el `workflow_dispatch` del commit anterior) y no hay manera de confirmar desde fuera que surtió efecto. Y la tabla de diagnóstico del `RUNBOOK §7` ya contempla "cachéo del edge sirviendo una versión anterior" como hipótesis: sin una versión visible en la propia página, esa hipótesis exige entrar en la VM para compararla con lo desplegado. *(Alcance acotado al implementar: el badge delata que el edge sirve una **página** cacheada antigua, no que sirva chunks JS antiguos con HTML fresco — ver la corrección en `design.md`.)*

Hay además un fallo silencioso posible: backend y frontend se despliegan con el mismo `IMAGE_TAG`, pero un `restart` manual o un `pull` del tag móvil `dev` puede desalinearlos sin que nada avise.

Este change sirve al **operador**, no a las personas de `steering/product.md` — no es funcionalidad de producto y no compite con la prioridad de entrega del PRD §30. Es herramienta de diagnóstico, y se justifica porque el CD a dev ya está vivo y cada deploy y cada rollback posterior paga el coste de no tenerla.

Decisiones cerradas en el análisis previo (2026-07-30) y por tanto **no reabiertas en `/sdd:design`**:

- **Esquema híbrido derivado** `<base>+<fecha-build>.<sha-corto>`. Se descartó SemVer con git tags porque introduce ceremonia de release (tag, CHANGELOG, política de bump) sobre un CD que despliega en cada push a `main`; se descartó "solo SHA" porque no da ninguna noción de versión de producto. El esquema elegido deja el hueco para adoptar SemVer real más adelante sin rediseñar nada.
- **Horneado, no variable de runtime.** Una variable de compose reporta lo que compose cree, no lo que la imagen es — miente justo en el fallo que queremos detectar. *(La justificación original añadía "y en el frontend solo un valor dentro del bundle detecta que el edge sirve JS antiguo". Se retira: verificado en la sección 4 que el badge, al ser Server Component, viaja en el HTML y no en `.next/static`, así que delata una página cacheada antigua pero no chunks JS antiguos con HTML fresco. El argumento de fondo —una identidad horneada no puede mentir sobre qué imagen corre— no depende de eso.)*
- **Pareo pantalla↔PR sin trabajo manual.** El repo mergea con merge commits (`Merge pull request #24 from …`), así que el subject del `github.sha` que dispara el deploy ya contiene el número de PR y se extrae en el build sin llamadas a la API ni permisos extra.

## What changes

Después de este change, **abrir la app dice qué versión está corriendo, y un clic lleva al PR que la produjo**.

El CD calcula, en cada build, un **bloque de procedencia** (versión, commit completo, PR, fecha de build, run de Actions, ref) y lo **hornea** en las dos imágenes: como `ENV` en la etapa `prod` del backend, y en el frontend en dos clases — `NEXT_PUBLIC_*` para lo que pinta el badge y `ENV` planas server-only para el resto. El mismo bloque se emite como labels OCI `org.opencontainers.image.{source,revision,version,created}`, de modo que `docker inspect` desde la VM y la página del package en GHCR quedan pareados igual — la vía de bajo nivel gana el mismo pareo, no lo pierde.

El backend expone **`/version`**, deliberadamente fuera de `/api/v1` y junto a `/health`, porque es un endpoint operativo y no una superficie de producto. El frontend lo lee **desde el servidor** por la red interna del compose (`BACKEND_INTERNAL_URL`), no desde el navegador: es la primera integración frontend→backend real del proyecto y se apoya en el seam que `frontend/lib/config/server.ts` dejó escrito para exactamente esto.

En pantalla, dos superficies con distinta divulgación: un **badge** con la cadena de versión, visible en todo el shell operativo incluida la pantalla de login (para poder diagnosticar sin poder entrar), y un **panel de procedencia** en la superficie de operación (workspace) que compara las versiones de frontend y backend y avisa si difieren.

Los **enlaces** al PR, al commit y al run del deploy quedan **aplazados**: el workspace no está autenticado —`auth-tenancy` no tocó el frontend—, así que cualquier dato entregado al panel se serializa en el HTML de una página anónima. Publicar ahí el nombre del repositorio privado y el número de PR es exactamente la divulgación que D6 evita, así que esos campos no se resuelven todavía. El panel muestra lo que ya era público por decisión (cadenas de versión, SHA corto, fecha de build) y los enlaces aparecen solos cuando el frontend gane autenticación.

## Requirements

### R1 — Identidad de build horneada en las dos imágenes

**As a** operador, **I want** que cada imagen lleve dentro su propia identidad de build, **so that** lo que veo no pueda mentir sobre lo que está corriendo.

Acceptance criteria:

1. WHEN el CD construye las imágenes de backend y frontend, THE SYSTEM SHALL calcular un bloque de procedencia con: cadena de versión `<base>+<fecha-build>.<sha-corto>`, commit completo (`github.sha`), número de PR, fecha de build ISO 8601 UTC, `run_id` de Actions y `ref_name`.
2. THE SYSTEM SHALL pasar ese bloque como **build-args** y hornearlo dentro de cada imagen: `ENV` en la etapa `prod` de `backend/devops/Dockerfile`, y en `frontend/devops/Dockerfile` **en dos clases** — `NEXT_PUBLIC_*` en la etapa `builder` para las dos que alimentan el badge (entran en `PublicRuntimeConfig` y cruzan al navegador), y `ENV` planas en la etapa `prod` para el resto (SHA completo, PR, `run_id`, `ref`, URL del repositorio), que solo lee el servidor de Next. *(Redacción corregida al implementar: la original decía "para que quede inlineado en el bundle de Next standalone", y eso no describe lo que ocurre — el badge es Server Component, así que la cadena viaja en el HTML servido. Ver la corrección de alcance en `design.md`.)*
3. THE SYSTEM SHALL NOT introducir ninguna variable de runtime en `docker-compose.deploy.yml` ni en el `.env` que rinda la versión — la fuente es la imagen.
4. THE SYSTEM SHALL emitir en ambas imágenes los labels `org.opencontainers.image.source`, `.revision`, `.version` y `.created` con los mismos valores.
5. THE SYSTEM SHALL construir las dos imágenes de un mismo deploy con **idéntica** cadena de versión y commit.
6. WHEN el commit que dispara el build es un merge commit de PR, THE SYSTEM SHALL extraer el número de PR del subject del commit (`git log -1 --format=%s`, patrón `#<n>`), sin llamadas a la API de GitHub ni permisos adicionales.
7. IF el subject no contiene un número de PR (push directo a `main`, o `workflow_dispatch` sobre un commit sin PR), THEN THE SYSTEM SHALL registrar el campo como ausente y continuar el build — nunca fallarlo.
8. THE SYSTEM SHALL mantener intacto el esquema de tags actual (`sha-<commit>` + `dev`) y el pineado por `${IMAGE_TAG}` del compose de deploy.
9. WHERE la imagen se construye en local (target `dev`, donde el frontend corre `npm run dev` y nunca ejecuta `npm run build`), THE SYSTEM SHALL rendir la identidad como local/desconocida sin fallar el arranque. THE SYSTEM SHALL declarar cualquier variable que el frontend necesite en dev local **explícitamente** en el bloque `environment:` de su servicio en `docker-compose.yml`, siguiendo el patrón que ya usa `NEXT_PUBLIC_APP_ENV: ${NEXT_PUBLIC_APP_ENV:-local}`: ese servicio **no tiene `env_file: .env`** a propósito desde `auth-tenancy` (el `.env` lleva ahora `JWT_SECRET_KEY` y `BOOTSTRAP_*_PASSWORD`, que el frontend no debe ver).

### R2 — El backend expone su procedencia en `/version`

**As a** operador o script de diagnóstico, **I want** preguntarle al backend qué versión es, **so that** pueda verificarlo con `curl` y el frontend pueda mostrarlo.

Acceptance criteria:

1. THE SYSTEM SHALL exponer `GET /version` devolviendo el bloque de procedencia horneado como JSON, con fechas ISO 8601 UTC (`steering/backend.md`).
2. THE SYSTEM SHALL montar `/version` **fuera** de `API_V1_PREFIX`, junto a `/health`, porque versiona el *build* y no la *API* — el versionado de la API es `/api/v1` (PRD §23) y este change no lo toca.
3. THE SYSTEM SHALL responder sin acceder a la base de datos ni a Redis, de modo que `/version` conteste aunque Postgres esté caído.
4. THE SYSTEM SHALL NOT modificar el contrato de `/health` (`{"status":"ok"}`), consumido por el healthcheck del contenedor y por los `depends_on` de `docker-compose.deploy.yml` y `docker-compose.yml`.
5. THE SYSTEM SHALL servir `/version` sin autenticación, como decisión explícita y documentada, y THE SYSTEM SHALL NOT incluir en su respuesta la URL del repositorio ni el título del PR (solo el número).
6. IF alguno de los campos horneados falta (imagen construida a mano, en local, o build-arg no pasado), THEN THE SYSTEM SHALL devolverlo como `null` o `"unknown"` en vez de fallar la petición.
7. THE SYSTEM SHALL añadir `("GET", "/version")` a `ANONYMOUS_ENDPOINTS` de `backend/tests/test_route_authorization.py`. Ese test de `auth-tenancy` exige que **toda** ruta fuera de una allowlist explícita declare una dependencia de autorización, y está keyeado por `(MÉTODO, path)`: sin esa entrada, `/version` anónimo **rompe la suite**. La edición es deliberada y es un diff visible, que es justo el diseño de ese test.
8. THE SYSTEM SHALL dejar el test siguiendo rojo para cualquier **otra** ruta anónima nueva: la allowlist crece solo con `/version` y THE SYSTEM SHALL NOT relajar el criterio (ni pasar a allowlist por path sin verbo, ni exceptuar por prefijo).
9. THE SYSTEM SHALL NOT añadir un `Permission` nuevo al enum de `app/auth/domain/policy.py` para esta ruta: hoy solo contiene permisos self-service (`READ_OWN_PROFILE`, `MANAGE_OWN_SESSION`) y añadir uno ampliaría el modelo de autorización por una ruta que se ha decidido anónima.
10. THE SYSTEM SHALL leer los campos horneados a través de `Settings` en `backend/app/core/config.py`, declarándolos **con valor por defecto**. `Settings` se instancia en tiempo de import (`settings = Settings()`) y `extra="ignore"`, así que un campo sin default convertiría una imagen construida sin build-args en un `ValidationError` al arrancar — el patrón opuesto al de `jwt_secret_key`, que es requerido *a propósito*. La versión nunca debe poder impedir el arranque.
11. THE SYSTEM SHALL registrar `/version` dentro de `create_app()`, junto a `/health`, siguiendo la decisión D2 de `auth-tenancy` (`/health` se queda en la raíz porque moverlo rompe el healthcheck; `/version` va ahí porque es operativo, no producto).
12. THE SYSTEM SHALL añadir `backend/tests/test_version.py` con la misma forma que el `test_health.py` existente (`ASGITransport` sobre `app.main:app`).
13. THE SYSTEM SHALL quedar verde en el gate `backend-tests` (`.github/workflows/backend-tests.yml`, capacidad `specs/backend-ci.md`), que corre **sin filtro de `paths`** en cada Pull Request y ejecuta `alembic upgrade head`, `alembic check`, la suite completa y `alembic downgrade base`.
14. THE SYSTEM SHALL NOT introducir ninguna tabla, modelo ni migración: la identidad de build vive en la imagen, no en la base de datos, así que `alembic check` y el ciclo `upgrade`/`downgrade` del gate quedan intactos.

### R3 — Badge de versión visible al abrir la app

**As a** propietaria u operador, **I want** ver la versión desplegada nada más abrir la app, **so that** no dependa de conectarme por SSH para saberlo.

Acceptance criteria:

1. THE SYSTEM SHALL mostrar la cadena de versión del frontend en el shell, en una posición estable y legible en móvil (mobile-first, `steering/frontend.md`).
2. THE SYSTEM SHALL mostrar el badge también **sin sesión** (pantalla de login), para permitir diagnóstico cuando no se puede entrar.
3. THE SYSTEM SHALL renderizar el badge **exclusivamente** a partir de la configuración horneada, sin ninguna petición de red, de modo que no pueda fallar ni tardar.
4. THE SYSTEM SHALL exponer los campos nuevos añadiéndolos explícitamente a `PublicRuntimeConfig` (`frontend/lib/config/public.ts`), respetando su allowlist — nunca esparciendo `process.env`.
5. THE SYSTEM SHALL declarar toda string visible del badge en `frontend/locales/es/` y `frontend/locales/en/`, sin nada hardcodeado.
6. THE SYSTEM SHALL NOT incluir en el badge la URL del repositorio ni el título del PR.
7. THE SYSTEM SHALL NOT mostrar el badge en el portal de huésped (`/guest/[token]`): es una superficie para personas ajenas a la operación, y la versión no les aporta nada. *(Interpretación acotada de la decisión "visible en todo el shell"; si el usuario prefiere incluirlo, se amplía en design.)*

### R4 — Pareo con el PR desde la propia pantalla

**As a** operador que ve una versión en pantalla, **I want** llegar al PR, al commit y al run de deploy que la produjeron, **so that** pueda saber qué cambió sin buscar a mano por SHA.

Acceptance criteria:

1. THE SYSTEM SHALL ofrecer un panel de procedencia, alcanzable desde el badge, con: cadena de versión, commit corto y completo, número de PR, fecha de build y `run_id`.
2. THE SYSTEM SHALL enlazar el número de PR a `…/pull/<n>`, el commit a `…/commit/<sha>` y el `run_id` a `…/actions/runs/<id>`.
3. THE SYSTEM SHALL mostrar ese panel **solo en la superficie autenticada de operación** (workspace), y THE SYSTEM SHALL NOT mostrarlo en login, en las apps de campo ni en el portal de huésped.
4. WHERE el campo de PR está ausente (R1.7), THE SYSTEM SHALL indicar "push directo, sin PR" en vez de un enlace roto.
5. THE SYSTEM SHALL declarar en `locales/es` y `locales/en` todas las strings del panel.
6. WHILE la superficie de operación no esté detrás de autenticación real, THE SYSTEM SHALL **NO resolver** el número de PR, el SHA completo, el `run_id`, el `ref` ni la URL del repositorio, de modo que no lleguen al navegador en absoluto, y THE SYSTEM SHALL omitir esas filas del panel en vez de mostrarlas como "desconocido". *(Criterio añadido el 2026-07-30 tras el panel de seguridad, que demostró que esos valores viajaban en el payload RSC de `/dashboard` —página anónima— y por tanto eran legibles con un `curl` por cualquiera. Cerrar el snapshot público no bastaba: los mismos datos salían por el camino de al lado. Decisión del usuario: aplazar los enlaces hasta que el frontend tenga autenticación, aceptando que el pareo con el PR vuelva a ser de dos pasos vía el SHA corto.)*
7. WHEN la superficie de operación pase a estar autenticada (entrada `dashboard-web`), THE SYSTEM SHALL empezar a resolver y enlazar esos campos sin más cambios que invertir una única condición de servidor.
8. THE SYSTEM SHALL tratar esa ubicación como **estructural y no como frontera de seguridad**, y THE SYSTEM SHALL NOT colocar en el panel ningún dato que requiera protección real. Hecho verificado: `auth-tenancy` **no toca el frontend** (0 ficheros bajo `frontend/`), así que tras su merge la UI sigue sin login, sin sesión y sin control de acceso; "solo en workspace" significa hoy "en la superficie de operación por registro de rutas", nada más.
7. WHEN el frontend gane autenticación real (entrada `dashboard-web` del roadmap), THE SYSTEM SHALL heredar ese control sin cambios en el panel — es decir, el panel debe colgar de la superficie que pasará a estar protegida, no de una comprobación propia inventada aquí.

### R5 — Deriva entre frontend y backend detectada, sin romper el shell

**As a** operador, **I want** que se avise si frontend y backend no corren la misma versión, **so that** un deploy a medias o un `restart` con el tag móvil no pase inadvertido.

Acceptance criteria:

1. THE SYSTEM SHALL leer la versión del backend **desde el servidor** del frontend, contra `BACKEND_INTERNAL_URL` por la red interna del compose, usando el seam de `frontend/lib/config/server.ts`.
2. THE SYSTEM SHALL NOT hacer esa petición desde el navegador ni exponer `/version` al exterior por el túnel para conseguirla.
3. WHEN las versiones de frontend y backend difieren, THE SYSTEM SHALL mostrar un aviso visible que indique ambas.
4. IF el backend no responde, responde con error, o tarda más que un timeout corto y explícito, THEN THE SYSTEM SHALL mostrar la versión del backend como desconocida y **renderizar el shell con normalidad** — el shell debe seguir levantando sin backend (invariante R8.1 de `frontend-foundation`).
5. THE SYSTEM SHALL aplicar a esa lectura un timeout acotado, de modo que un backend colgado no bloquee el render.
6. THE SYSTEM SHALL NOT introducir un `rewrite` de Next ni una regla de ingress para conseguir esta lectura. `auth-tenancy` deja en el roadmap la entrada `api-ingress-routing`, cuya inclinación técnica (OQ2 de su design) es exactamente un `rewrite` de Next hacia `BACKEND_INTERNAL_URL` para dar a la API un camino desde internet. Cuando eso llegue, `/version` **no** debe quedar expuesto como efecto colateral de un patrón demasiado amplio: si acaba siéndolo, ha de ser una decisión consciente y no un descuido, y R2.5 (anónimo por diseño) es lo que la hace tolerable.

### R6 — Una sola fuente de verdad para la versión base, y documentada

**As a** quien mantiene el proyecto, **I want** que la parte fija de la versión viva en un solo sitio y que el flujo esté documentado, **so that** no vuelva a haber dos `0.1.0` muertos y desincronizados.

Acceptance criteria:

1. THE SYSTEM SHALL designar **una** fuente de verdad para la base de versión y derivar o validar la otra a partir de ella; hoy `backend/pyproject.toml` y `frontend/package.json` declaran `0.1.0` de forma independiente y ninguna se usa.
2. IF las dos declaraciones divergen, THEN THE SYSTEM SHALL fallar en CI, no en silencio.
3. THE SYSTEM SHALL documentar en `RUNBOOK.md` §6.4 cómo confirmar un rollback usando el badge y `/version`, y en la tabla de diagnóstico de §7 cómo el badge de la página descarta (o confirma) el cachéo del edge, con la limitación de que no cubre chunks JS antiguos servidos con HTML fresco.
4. THE SYSTEM SHALL documentar que, por el filtro de paths del CD (`backend/**`, `frontend/**`, `docker-compose.deploy.yml`, el propio workflow), la versión en pantalla corresponde al **último commit que disparó build**, no al último commit de `main` — apuntar a un PR de varios merges atrás es correcto y no es deriva.
5. THE SYSTEM SHALL documentar que el pareo depende de la estrategia de merge: funciona con merge commits y con squash (`título (#42)`), y se rompería **en silencio** con rebase, cuyo plan B es `gh api /repos/{repo}/commits/{sha}/pulls` con `pull-requests: read`.
6. THE SYSTEM SHALL cumplir `steering/documentation.md`: `docs/<capability>.md` para esta capacidad, README raíz, y `.env.example`/`.env.deploy.example` si el change introdujera alguna variable (no se espera: la identidad va horneada, R1.3).

## Out of scope

- **SemVer real con git tags, releases y CHANGELOG.** Decisión explícita del análisis previo: se adopta cuando haya releases que ordenar. El esquema híbrido de R1 deja el hueco.
- **Versionado de la API.** `/api/v1` ya existe (PRD §23) y no se toca. Este change versiona el *build*.
- **Observabilidad.** Métricas, tracing, logs estructurados y alertas son otro problema; `/version` no es un endpoint de salud ni de métricas.
- **Rollback automático.** Sigue siendo manual por SHA (`RUNBOOK §6.4`) — decisión de diseño de `app-deploy-dev`. Este change solo permite *confirmar* que un rollback surtió efecto.
- **staging/prod.** Solo `dev`, único entorno existente. El mecanismo es reutilizable, pero no se declara soportado en otros entornos.
- **Versiones de los servicios de terceros** (`postgres:16`, `redis:7`, `cloudflared` pineado por dígest): ya están pineadas en el compose y no forman parte de la identidad de la app.
- **Historial de despliegues en la UI.** Ver qué versión hubo antes es trabajo de Actions y de GHCR, no de la app.
- **Cambiar la estrategia de merge o la limpieza de ramas remotas.** Solo se documenta el plan B si algún día se pasa a rebase (R6.5).

## Affected specs

- `sdd/specs/app-version-visibility.md` — **crear** *(no existe aún — se creará al archivar)*: la capacidad completa (identidad horneada, `/version`, badge, panel de procedencia, detección de deriva).
- `sdd/specs/app-deploy-dev.md` — modificar: el build pasa a calcular procedencia, pasarla como build-args y emitir labels OCI; se documenta que la extracción del PR depende del merge commit.
- `sdd/specs/frontend-foundation.md` — modificar: `PublicRuntimeConfig` gana campos, el shell gana una superficie nueva, y el seam servidor→backend de `lib/config/server.ts` pasa a tener su primer consumidor real.

- `sdd/specs/auth-tenancy.md` — modificar *(ya existe: `auth-tenancy` se archivó el 2026-07-30)*: la allowlist de rutas anónimas gana `/version`, que es una afirmación de seguridad y pertenece a la spec que la establece (§"deny by default", donde ya se razona el keyeo por `(método, path)`).
- `sdd/specs/backend-ci.md` — modificar *(añadida tras el hallazgo del panel de CI/CD)*: el gate `backend-tests` gana un step de paridad de versión que abarca **también** el frontend, mientras su Purpose acota hoy la capacidad a "la suite completa del backend". Hay que documentar ahí esa responsabilidad cruzada y por qué se acepta (es el único workflow que corre en cada PR sin filtro de `paths`, y el frontend no tiene gate propio todavía — su propia §Estado lo constata).

Fuera de `sdd/specs/`, este change toca `.github/workflows/deploy-dev.yml`, `backend/devops/Dockerfile`, `frontend/devops/Dockerfile`, `backend/app/main.py`, `backend/app/core/config.py`, `backend/tests/test_route_authorization.py`, `backend/tests/test_version.py` *(nuevo)*, `docker-compose.yml` (variable del frontend en dev), la capa `frontend/lib/config/`, el shell de `frontend/features/shell/`, `frontend/locales/{es,en}/`, `infra/environments/dev/RUNBOOK.md` §6.4 y §7, `docs/` y el README raíz.

## Dependencias y supuestos

`auth-tenancy` (PR #25) y `timeline-state-machine` (PR #18) **ya están mergeados y archivados**. Lo siguiente está verificado contra el `main` resultante (`628f59d`), no contra una rama ni supuesto:

**Los tres puntos de acople del backend siguen exactamente como se anticiparon** (releídos sobre el código mergeado, no sobre la rama):

- `backend/app/main.py` mantiene `create_app()`, `API_V1_PREFIX = "/api/v1"` y `/health` registrado inline dentro de la factoría → R2.11 vigente.
- `ANONYMOUS_ENDPOINTS` de `backend/tests/test_route_authorization.py` es idéntico al inspeccionado (7 entradas, keyeado por `(método, path)`) → R2.7/R2.8 vigentes y **necesarios**: sin la entrada, la suite se cae.
- `backend/app/core/config.py` sigue instanciando `settings = Settings()` en tiempo de import, con `extra="ignore"`, `jwt_secret_key` requerido por `Field(min_length=32)` y todo lo demás con default (ganó un campo, `bcrypt_max_concurrency`) → R2.10 vigente.

**El CD sigue limpio.** `main` no ha cambiado `.github/workflows/deploy-dev.yml` ni ninguno de los dos Dockerfiles respecto a lo que R1 asume.

**Novedad no prevista: existe un gate de CI del backend.** `auth-tenancy` añadió `.github/workflows/backend-tests.yml` y la capacidad `sdd/specs/backend-ci.md`. Corre **sin filtro de `paths` a propósito** (un required check con filtro deja el PR esperando para siempre un check que nunca llega), así que **este change se verifica ahí quiera o no**: R2.13 y R2.14 lo recogen.

**`timeline-state-machine` no interactúa.** Añadió `app/timeline/` con solo `domain/` e `infrastructure/`: **ninguna superficie HTTP**. `main.py` sigue incluyendo un único router (`auth_router`), así que no hay rutas nuevas que la allowlist tenga que considerar ni colisión posible con `/version`.

**Compatible en el frontend por ausencia**: `auth-tenancy` no tocó ni un fichero bajo `frontend/`. Ninguna colisión — y también ninguna autenticación de la que colgar R4, de ahí R4.6 y R4.7.

**Roce real en el compose de dev**, confirmado sobre el fichero mergeado: el servicio `frontend` de `docker-compose.yml` no tiene `env_file: .env` y declara sus variables una a una (`NEXT_PUBLIC_APP_ENV: ${NEXT_PUBLIC_APP_ENV:-local}`) — recogido en R1.9.

**Interacción a vigilar con `api-ingress-routing`** (entrada que dejó `auth-tenancy` en el roadmap): recogida en R5.6.

`ASSUMPTION`: el repo mantiene merge commits como estrategia (verificado sobre los últimos merges de `main`, no sobre los ajustes del repositorio, que no se consultaron).
