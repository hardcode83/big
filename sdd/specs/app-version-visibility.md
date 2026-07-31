# Visibilidad de la versión desplegada

## Purpose

Permite saber qué versión de la aplicación está corriendo **sin entrar en la VM**: el CD hornea
una identidad de build dentro de la imagen del frontend y en los labels OCI de ambas imágenes,
y el shell la muestra en un badge en el pie. Sirve al operador —confirmar un rollback (manual
por SHA, `RUNBOOK §6.4`), descartar el cachéo del edge— no a las personas de
`steering/product.md`: es herramienta de diagnóstico, no funcionalidad de producto.

Antes de esta capacidad la única identidad era el tag `sha-<commit>` que el CD escribe en el
`.env` de la máquina, legible solo por túnel SSH.

## Requirements

### La versión base y su composición

- THE SYSTEM SHALL definir la parte fija de la versión del producto en un fichero `VERSION` en
  la raíz del repositorio, en una línea.
- WHEN el CD construye las imágenes, THE SYSTEM SHALL componer en un **único** job la cadena
  canónica `<base>+<fecha-build>.<sha-corto>`, con una sola lectura del reloj que alimenta
  tanto la fecha de la cadena como el label `.created`.
- IF `VERSION` no existe, está vacío o no tiene forma `X.Y.Z`, THEN THE SYSTEM SHALL fallar el
  build nombrando el problema, antes de construir imagen alguna.
- THE SYSTEM SHALL NOT usar los campos `version` de `backend/pyproject.toml` ni
  `frontend/package.json` para nada: los declaran por convención de sus ecosistemas y **pueden
  divergir de `VERSION` sin que nada avise**. Comprobarlo en CI queda pendiente en la entrada
  de roadmap `app-version-provenance`.

### Identidad horneada en la imagen, nunca inyectada en runtime

- THE SYSTEM SHALL pasar `NEXT_PUBLIC_APP_VERSION` y `NEXT_PUBLIC_BUILD_COMMIT_SHORT` como
  build-args a la etapa `builder` de `frontend/devops/Dockerfile`, declarados al final de la
  etapa para no invalidar la caché de las capas de dependencias.
- THE SYSTEM SHALL emitir en **ambas** imágenes los labels
  `org.opencontainers.image.{source,revision,version,created}` con idénticos valores, de modo
  que `docker inspect` en la VM y la página del package en GHCR queden pareados con la UI.
- THE SYSTEM SHALL NOT introducir ninguna variable de runtime —ni en `docker-compose.deploy.yml`
  ni en el `.env` que el CD renderiza en la VM— que rinda la versión: la fuente es la imagen.
  Una variable de compose reporta lo que compose cree, no lo que la imagen es.
- THE SYSTEM SHALL excluir `.env*` del contexto de build del frontend: el `.gitignore` raíz los
  ignora, así que un `.env.local` de una máquina de desarrollo no está en git pero sí entraría
  por `COPY . .`, y `npm run build` inlinearía sus `NEXT_PUBLIC_*` en el bundle.
- WHERE la imagen se construye con el target `dev` (que corre `npm run dev` y nunca
  `npm run build`), THE SYSTEM SHALL rendir la identidad como `local` sin fallar el arranque,
  con las variables declaradas explícitamente en el bloque `environment:` del servicio
  `frontend` de `docker-compose.yml` — ese servicio **no tiene `env_file`** a propósito, porque
  el `.env` lleva `JWT_SECRET_KEY` y `BOOTSTRAP_*_PASSWORD`.
- THE SYSTEM SHALL mantener intactos el esquema de tags (`sha-<commit>` + el móvil `dev`) y el
  pineado por `${IMAGE_TAG}` del compose de deploy.

### El badge en el shell

- WHEN se abre la aplicación, THE SYSTEM SHALL mostrar la versión desplegada en un badge en el
  pie del shell, en la forma corta `<base>+<sha-corto>`.
- THE SYSTEM SHALL mostrarlo también **sin sesión** (`/login`) y en las apps de campo
  (`/cleaner`, `/tech`): es cuando más falta hace, porque si la aplicación está rota puede que
  no se pueda entrar.
- THE SYSTEM SHALL NOT renderizar el badge en el portal de huésped (`/guest/[token]`): es una
  superficie para personas ajenas a la operación.
- THE SYSTEM SHALL renderizar el badge **exclusivamente** desde la configuración horneada, sin
  ninguna petición de red, de modo que no pueda fallar ni tardar ni depender del backend.
- IF la imagen no lleva identidad horneada, THEN THE SYSTEM SHALL mostrar un texto localizado
  de versión desconocida, y THE SYSTEM SHALL NOT mostrar un badge vacío ni una cadena con
  forma de versión a medias — incluidos los casos en que la cadena existe pero su base queda
  vacía (`"+"`, `"  +abc123"`).
- THE SYSTEM SHALL exponer los dos campos añadiéndolos explícitamente a la allowlist de
  `PublicRuntimeConfig`, sin esparcir `process.env`, y THE SYSTEM SHALL NOT incluir en ese
  snapshot la URL del repositorio, el número de Pull Request, el SHA completo, el `run_id` ni
  el `ref`.
- THE SYSTEM SHALL declarar toda string visible del badge en `locales/es/` y `locales/en/`,
  resuelta en servidor y entregada como props — el badge es síncrono, porque un componente
  async anidado en el frame suspende el árbol entero del shell.
- THE SYSTEM SHALL reservar en la columna que contiene `topbar`/`main`/`footer` la altura del
  `BottomNavigation` fijo en móvil (`pb-16 md:pb-0`), de modo que el pie quede **por encima**
  de la barra y no debajo, y THE SYSTEM SHALL mantener el pie **fuera** del landmark `main`.

### Alcance de la divulgación, aceptado

- THE SYSTEM SHALL aceptar que la cadena de versión y el SHA corto sean legibles por cualquier
  llamante **anónimo**: `PublicRuntimeConfig` es un snapshot único que el layout raíz serializa
  en **todas** las superficies, así que viajan en el HTML incluso donde el badge no se pinta
  (el portal de huésped). No es divulgación nueva —quien alcanza `/guest/<token>` alcanza
  `/login` en el mismo origen—; lo que se evita es *mostrárselo* a un huésped.
- THE SYSTEM SHALL mantener fuera de la aplicación la URL del repositorio, el número de PR, el
  SHA completo y el `run_id`: no se hornean en ninguna parte del frontend. Reintroducirlos
  exige autenticación en el frontend y vive en `app-version-provenance`.

### Alcance frente al cachéo del edge

- WHERE el edge sirve una **página** cacheada de un despliegue anterior, THE SYSTEM SHALL
  delatarlo: el badge se renderiza en servidor, así que su valor viaja en el HTML.
- THE SYSTEM SHALL NOT detectar chunks de JavaScript antiguos servidos con HTML fresco — ese
  caso queda fuera y se diagnostica por los nombres de fichero en la pestaña Network.

### La versión del frontend es la versión del despliegue

- THE SYSTEM SHALL tratar la identidad del frontend como la del despliegue completo, sin
  endpoint de versión en el backend ni comparación entre ambos. El monorepo construye las dos
  imágenes del mismo commit en el mismo run, el job `deploy` depende de ambos builds y escribe
  una única `IMAGE_TAG`, y el compose pinea los **cuatro** servicios a ella: divergir exige
  intervención manual en la VM.
- WHERE un deploy falla a medias, THE SYSTEM SHALL dejar la deriva en la dirección
  conservadora: `frontend` declara `depends_on: backend: service_healthy`, así que el frontend
  no se recrea y sigue sirviendo el badge **antiguo**. El badge no puede afirmar un despliegue
  que el backend no tiene.
- IF backend y frontend dejan de desplegarse juntos (pipelines separados, escalado
  independiente, un hotfix de solo-backend, o un compose que deje de compartir `IMAGE_TAG`),
  THEN THE SYSTEM SHALL reabrir esta decisión: la premisa se rompe y la detección de deriva
  recupera su sentido.

### Lo que la versión en pantalla significa

- THE SYSTEM SHALL documentar que, por el filtro de rutas del CD (`backend/**`, `frontend/**`,
  `docker-compose.deploy.yml` y el propio workflow), la versión mostrada corresponde al último
  commit que **disparó build**, no al último de `main`: apuntar a un commit de varios merges
  atrás es correcto y no es deriva.
- THE SYSTEM SHALL documentar que el despliegue pinea por el tag **mutable** `sha-<commit>` y
  no por dígest, de modo que la forma corta del badge es idéntica para dos builds distintos del
  mismo commit; solo `org.opencontainers.image.created` los distingue.

## Key files

- `VERSION` — la parte fija de la versión del producto.
- `.github/workflows/deploy-dev.yml` — job `provenance` (composición y validación de `VERSION`),
  build-args del frontend y labels OCI en ambos builds.
- `frontend/devops/Dockerfile` — `ARG`/`ENV` `NEXT_PUBLIC_*` en la etapa `builder`.
- `frontend/.dockerignore` — exclusión de `.env*` del contexto de build.
- `frontend/lib/config/public.ts` — `appVersion` y `buildCommitShort` en la allowlist pública.
- `frontend/features/shell/components/version-badge.tsx` — `formatBuildVersion` y el badge.
- `frontend/features/shell/components/shell-footer.tsx`, `shell-frame.tsx` — pie y slot `footer`.
- `frontend/locales/{es,en}/common.json` — claves `version.*`.
- `docker-compose.yml` — las dos `NEXT_PUBLIC_*` del servicio `frontend` en dev local.
- `docs/app-version-visibility.md` — cómo se opera; `infra/environments/dev/RUNBOOK.md` §6.4 y §7.

## Estado

Desplegado y verificado en `dev` el 2026-07-31 (PR #27, merge `5872022`): el badge muestra
`0.1.0+5872022` en `/login`, `/dashboard`, `/cleaner` y `/tech`, y está ausente en
`/guest/<token>`.

**Pendiente de comprobar sobre la VM**: que los labels OCI de las dos imágenes lleven idénticos
valores. Los valores son idénticos por construcción (un único job `provenance` alimenta ambos
builds), pero que aterrizaran en las imágenes publicadas no se ha verificado — el token de `gh`
disponible no tiene `read:packages` y el package es privado.

**Mejora ya identificada**: el badge recorta la fecha de build, decisión que se tomó porque la
fecha se mostraría en el panel de procedencia; ese panel se retiró al recortar el alcance del
change, así que hoy la fecha solo es accesible por `docker inspect` o en el código fuente de la
página. Lo corrige la entrada de roadmap `app-version-badge-date`.
