# Proposal: app-version-visibility

> **Alcance recortado el 2026-07-30.** La versión original de este proposal cubría además el
> pareo pantalla↔PR (panel de procedencia con enlaces), la detección de deriva
> frontend↔backend con un endpoint `/version` en el backend, y un gate de CI de paridad de
> versión. Se implementó entero (3.039 líneas) y el usuario decidió recortarlo a lo que
> pidió originalmente: **ver la versión desplegada al abrir la app**. Lo retirado vive en la
> entrada de roadmap `app-version-provenance`, con el porqué. Este documento describe solo
> lo que queda.

## Why

Hoy **no hay forma de saber qué está desplegado sin entrar en la VM**. La única identidad es
el tag de imagen (`sha-<commit>` + el móvil `dev`), que el CD escribe en el `.env` de la
máquina; para leerla hay que abrir un túnel SSH y hacer `grep IMAGE_TAG .env`. No hay git
tags, ni SemVer, ni labels OCI en las imágenes, así que `docker inspect` tampoco ayuda.

Eso encarece dos operaciones ya documentadas como manuales: el **rollback por SHA**
(`RUNBOOK §6.4`), que no se puede confirmar desde fuera, y **descartar el cachéo del edge**,
que la tabla de diagnóstico del `RUNBOOK §7` ya contempla como hipótesis.

Sirve al **operador**, no a las personas de `steering/product.md`: es herramienta de
diagnóstico, no funcionalidad de producto, y no compite con la prioridad de entrega del
PRD §30.

Decisiones cerradas en el análisis previo:

- **Esquema híbrido derivado** `<base>+<fecha-build>.<sha-corto>`. Se descartó SemVer con
  git tags: introduce ceremonia de release sobre un CD que despliega en cada push a `main`.
- **Horneado, no variable de runtime.** Una variable de compose reporta lo que compose cree,
  no lo que la imagen es.

## What changes

El CD compone la cadena de versión **una sola vez** —leyendo la base de `VERSION`, con la
fecha de build y el commit corto— y la hornea en la imagen del frontend como build-args
`NEXT_PUBLIC_*`. Las dos imágenes reciben además los mismos **labels OCI**, así que
`docker inspect` en la VM y la página del package en GHCR quedan pareados.

En pantalla, un **badge** en el pie del shell con la cadena de versión, visible también en
`/login` sin sesión.

## Requirements

### R1 — Identidad de build horneada en la imagen

**As a** operador, **I want** que la imagen lleve dentro su propia identidad, **so that** lo
que veo no pueda mentir sobre lo que está corriendo.

Acceptance criteria:

1. WHEN el CD construye las imágenes, THE SYSTEM SHALL componer, en un único sitio, la
   cadena `<base>+<fecha-build>.<sha-corto>`, leyendo la base de `VERSION` y usando una sola
   lectura del reloj para la fecha y para el label `.created`.
2. IF `VERSION` no existe, está vacío, o no tiene forma `X.Y.Z`, THEN THE SYSTEM SHALL
   fallar el build con un mensaje que nombre el problema.
3. THE SYSTEM SHALL pasar `NEXT_PUBLIC_APP_VERSION` y `NEXT_PUBLIC_BUILD_COMMIT_SHORT` como
   build-args a la etapa `builder` de `frontend/devops/Dockerfile`.
4. THE SYSTEM SHALL NOT introducir ninguna variable de runtime en `docker-compose.deploy.yml`
   ni en el `.env` que rinda la versión — la fuente es la imagen.
5. THE SYSTEM SHALL emitir en **ambas** imágenes los labels `org.opencontainers.image.source`,
   `.revision`, `.version` y `.created`, con idénticos valores.
6. WHERE la imagen se construye en local (target `dev`, que corre `npm run dev` y nunca
   `npm run build`), THE SYSTEM SHALL rendir la identidad como local sin fallar el arranque,
   con las variables declaradas explícitamente en el bloque `environment:` del servicio
   `frontend` de `docker-compose.yml` — ese servicio **no tiene `env_file`** a propósito.
7. THE SYSTEM SHALL mantener intactos el esquema de tags (`sha-<commit>` + `dev`) y el
   pineado por `${IMAGE_TAG}` del compose de deploy.

### R2 — Badge de versión visible al abrir la app

**As a** propietaria u operador, **I want** ver la versión desplegada nada más abrir la app,
**so that** no dependa de conectarme por SSH para saberlo.

Acceptance criteria:

1. THE SYSTEM SHALL mostrar la cadena de versión en el pie del shell, legible en móvil
   (mobile-first, `steering/frontend.md`), en la forma corta `<base>+<sha-corto>`.
2. THE SYSTEM SHALL mostrarla también **sin sesión** (pantalla de login) y en las apps de
   campo, para permitir diagnóstico cuando no se puede entrar.
3. THE SYSTEM SHALL renderizar el badge **exclusivamente** desde la configuración horneada,
   sin ninguna petición de red, de modo que no pueda fallar ni tardar.
4. THE SYSTEM SHALL exponer los campos añadiéndolos explícitamente a `PublicRuntimeConfig`
   (`frontend/lib/config/public.ts`), respetando su allowlist — nunca esparciendo
   `process.env`.
5. THE SYSTEM SHALL declarar toda string visible en `locales/es/` y `locales/en/`.
6. THE SYSTEM SHALL NOT renderizar el badge en el portal de huésped (`/guest/[token]`): es
   una superficie para personas ajenas a la operación. **Divulgación aceptada y verificada**:
   `PublicRuntimeConfig` es un snapshot único que el layout raíz serializa en **todas** las
   superficies, así que la cadena de versión y el SHA corto viajan en el HTML del portal de
   huésped aunque el badge no se pinte. Es la misma divulgación que ya se acepta en `/login`
   —ambas son superficies anónimas—; lo que R2.6 evita es *mostrárselo* a un huésped.
7. IF la imagen no lleva identidad horneada, THEN THE SYSTEM SHALL mostrar un texto
   localizado de "versión desconocida", nunca un badge vacío ni algo con forma de versión.

### R3 — La versión base tiene un sitio, y está documentada

**As a** quien mantiene el proyecto, **I want** saber dónde se sube la versión y cómo se
opera, **so that** no haya que reconstruirlo por lectura del CD.

Acceptance criteria:

1. THE SYSTEM SHALL definir la base del producto en un fichero `VERSION` en la raíz.
2. THE SYSTEM SHALL documentar en `RUNBOOK.md` §6.4 cómo confirmar un rollback con el badge
   y con los labels OCI, y en la tabla de diagnóstico de §7 cómo interpretar un badge
   atrasado, con la limitación de que delata una página cacheada pero no chunks JS antiguos
   servidos con HTML fresco.
3. THE SYSTEM SHALL documentar que, por el filtro de paths del CD, la versión en pantalla
   corresponde al último commit que **disparó build**, no al último de `main`.
4. THE SYSTEM SHALL cumplir `steering/documentation.md`: `docs/app-version-visibility.md` y
   README raíz. No se espera variable de entorno nueva (la identidad va horneada, R1.4).
5. THE SYSTEM SHALL dejar constancia de que `backend/pyproject.toml` y
   `frontend/package.json` declaran un `version` que **hoy nadie usa y puede divergir de
   `VERSION` sin aviso** — comprobarlo en CI queda en `app-version-provenance`.

## Out of scope

- **El pareo pantalla↔PR** (panel de procedencia, enlaces al PR/commit/run, extracción del
  número de PR del subject del commit) → entrada `app-version-provenance`. Exige que el
  frontend tenga autenticación antes: los enlaces nombran el repositorio privado y hoy el
  HTML de todas las páginas es público.
- **La detección de deriva frontend↔backend**, y con ella el endpoint `/version` del backend
  y el Route Handler del frontend: **descartada, no aplazada**. El monorepo construye ambas
  imágenes del mismo commit y el compose pinea los cuatro servicios al mismo `${IMAGE_TAG}`,
  así que divergir exige intervención manual en la VM; y los labels OCI de ambas imágenes ya
  permiten comprobarlo con dos `docker inspect`. Razonamiento y condición de revisión en la
  decisión D6 del design.
- **El gate de paridad de versión** entre `VERSION` y los dos manifiestos → misma entrada.
- **SemVer real con git tags, releases y CHANGELOG.** El esquema híbrido deja el hueco.
- **Versionado de la API.** `/api/v1` ya existe (PRD §23); esto versiona el *build*.
- **Rollback automático.** Sigue siendo manual por SHA; esto solo permite *confirmarlo*.
- **staging/prod.** Solo `dev`, único entorno existente.

## Affected specs

- `sdd/specs/app-version-visibility.md` — **crear** *(no existe aún — se creará al
  archivar)*: identidad horneada, labels OCI y badge.
- `sdd/specs/app-deploy-dev.md` — modificar: el CD gana el job que compone la identidad, los
  build-args del frontend y los labels OCI en ambas imágenes.
- `sdd/specs/frontend-foundation.md` — modificar: `PublicRuntimeConfig` gana dos campos y
  `ShellFrame` un slot `footer`.

Fuera de `sdd/specs/`: `.github/workflows/deploy-dev.yml`, `frontend/devops/Dockerfile`,
`docker-compose.yml`, `frontend/.dockerignore`, la capa `frontend/lib/config/`, el shell de
`frontend/features/shell/`, `frontend/locales/{es,en}/`, `VERSION`,
`infra/environments/dev/RUNBOOK.md`, `docs/` y el README raíz.
