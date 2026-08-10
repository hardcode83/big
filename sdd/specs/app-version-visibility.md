# Visibilidad de la versión desplegada

## Purpose

Permite saber qué versión de la aplicación está corriendo **sin entrar en la VM**: el CD hornea
una identidad de build dentro de la imagen del frontend y en labels OCI compatibles con la
frontera de cada imagen,
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
- THE SYSTEM SHALL mantener `VERSION`, `backend/pyproject.toml` y
  `frontend/package.json` en parity; `make check-version-parity` lo comprueba desde el host y
  falla identificando cualquier valor ausente, vacío o divergente.

### Identidad horneada en la imagen, nunca inyectada en runtime

- THE SYSTEM SHALL pasar `NEXT_PUBLIC_APP_VERSION` y `NEXT_PUBLIC_BUILD_COMMIT_SHORT` como
  build-args a la etapa `builder` de `frontend/devops/Dockerfile`, declarados al final de la
  etapa para no invalidar la caché de las capas de dependencias.
- THE SYSTEM SHALL emitir en la imagen backend los labels
  `org.opencontainers.image.{source,revision,version,created}`. La imagen frontend SHALL emitir
  únicamente `org.opencontainers.image.revision` con el SHA corto, `version` y `created`; no
  SHALL incluir `source`, la URL privada del repositorio, el SHA completo ni la provenance
  privada completa. La identidad pública `version` debe seguir siendo la misma que muestra la UI.
- La identidad pública SHALL seguir originándose en la imagen frontend mediante build args. El
  CD SHALL escribir además `APP_VERSION` únicamente en la configuración privada del backend,
  para que el endpoint autenticado de provenance devuelva la misma identidad; esa variable no
  se entrega al frontend ni sustituye la identidad horneada que pinta la UI.
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
  pie del shell, con la **cadena canónica completa** `<base>+<fecha-build>.<sha-corto>` —la
  misma que llevan los labels OCI—, sin recortarla.
- THE SYSTEM SHALL mostrarlo también **sin sesión** (`/login`) y en las apps de campo
  (`/cleaner`, `/tech`): es cuando más falta hace, porque si la aplicación está rota puede que
  no se pueda entrar.
- THE SYSTEM SHALL NOT renderizar el badge en el portal de huésped (`/guest/[token]`): es una
  superficie para personas ajenas a la operación.
- THE SYSTEM SHALL renderizar el badge **exclusivamente** desde la configuración horneada, sin
  ninguna petición de red, de modo que no pueda fallar ni tardar ni depender del backend.
- IF la imagen no lleva identidad horneada **o la identidad no tiene la forma admitida**, THEN
  THE SYSTEM SHALL mostrar un texto localizado de versión desconocida, y THE SYSTEM SHALL NOT
  mostrar un badge vacío ni una cadena con forma de versión a medias — incluidos los casos en
  que la cadena existe pero su base queda vacía (`"+"`, `"  +abc123"`) o su `+` no lleva nada
  (`"0.1.0+"`). Las dos causas son **indistinguibles en pantalla** a propósito, y se separan
  desde fuera comparando con `org.opencontainers.image.version` de la imagen.
- THE SYSTEM SHALL exponer los dos campos añadiéndolos explícitamente a la allowlist de
  `PublicRuntimeConfig`, sin esparcir `process.env`, y THE SYSTEM SHALL NOT incluir en ese
  snapshot la URL del repositorio, el número de Pull Request, el SHA completo, el `run_id` ni
  el `ref`.

### El límite valida la forma de la identidad, no solo el nombre de los campos

- THE SYSTEM SHALL admitir en el snapshot público **únicamente** `<base>` con forma `X.Y.Z`
  —opcionalmente seguida de `+<fecha-de-calendario-real>.<7 hex>`— o el literal `local`; y para
  el commit corto **únicamente** 7 caracteres hexadecimales. IF el valor horneado no encaja,
  THEN THE SYSTEM SHALL rendirlo como cadena vacía, que es el mismo caso que "sin identidad".
- THE SYSTEM SHALL hacer esa comprobación en `buildPublicRuntimeConfig()` y **no** en el
  componente que pinta el badge: React serializa el snapshot como prop en el payload RSC del
  layout raíz, así que un valor no vetado viaja en el HTML de **todas** las superficies —el
  portal de huésped incluido— por mucho que el badge decida no pintarlo. Validar en el
  componente solo limpia los píxeles.
- THE SYSTEM SHALL acotar cada componente por **valor** y no por cantidad de caracteres: el
  commit a 7 hex exactos (los dígitos decimales son subconjunto del hex, así que un rango
  `{7,12}` admite un `run_id` de Actions como si fuera un commit), el mes y el día a rangos de
  calendario reales (`\d{4}-\d{2}-\d{2}` son ocho dígitos libres), y la base a `X.Y.Z` (una
  clase de caracteres con tope de longitud dejaba pasar `0.1.0-<run_id>` y un prefijo hex de 32
  caracteres que `git rev-parse` resuelve a un commit). Un tope de longitud limita cuánto de un
  valor se filtra; no impide que se filtre.
- WHERE el CD deje de emitir esas formas, THE SYSTEM SHALL degradar a "versión desconocida" en
  vez de mostrar algo no vetado — falla cerrado.
- WHEN la forma producida por el CD deje de ser aceptada por el contrato público vigente del
  frontend, THE SYSTEM SHALL hacer fallar la verificación de congruencia.
- WHEN un Pull Request incluya cambios que afecten al productor CD o al consumidor público de
  identidad, THE SYSTEM SHALL incluir una verificación obligatoria de congruencia entre los
  checks de CI aplicables al Pull Request.
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

- THE SYSTEM SHALL tratar la identidad del frontend como la del despliegue completo y mantenerla
  congruente con `app_version` del endpoint autenticado `/api/v1/provenance`. El monorepo
  construye las dos imágenes del mismo commit en el mismo run, el job `deploy` depende de ambos
  builds y escribe una única `IMAGE_TAG`, y el compose pinea los **cuatro** servicios a ella:
  divergir exige intervención manual en la VM.
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
  no por dígest, así que un mismo commit puede construirse más de una vez y dar imágenes
  distintas con el mismo tag. La fecha del badge **separa builds de días distintos**; THE SYSTEM
  SHALL NOT pretender que separe dos builds del mismo commit **el mismo día** —la fecha canónica
  tiene granularidad de día (`%Y-%m-%d`)—, que es justo el caso de un `workflow_dispatch` para
  recuperar un deploy fallido: solo `org.opencontainers.image.created`, que lleva la hora, los
  distingue.

## Key files

- `VERSION` — la parte fija de la versión del producto.
- `.github/workflows/deploy-dev.yml` — job `provenance` (composición y validación de `VERSION`),
  build-args del frontend y labels OCI diferenciados por frontera de divulgación.
- `frontend/devops/Dockerfile` — `ARG`/`ENV` `NEXT_PUBLIC_*` en la etapa `builder`.
- `frontend/.dockerignore` — exclusión de `.env*` del contexto de build.
- `frontend/lib/config/public.ts` — `appVersion` y `buildCommitShort` en la allowlist pública,
  y los patrones `BAKED_VERSION`/`BAKED_COMMIT_SHORT` que vetan la forma antes de que el valor
  entre en el snapshot. Es la frontera de divulgación; el badge no decide nada de esto.
- `frontend/lib/config/build-identity-contract.json` — patrones y literales compartidos por el
  productor CD y la frontera pública.
- `frontend/scripts/build-identity.mjs` — composición, validación y publicación de outputs del
  job `provenance`.
- `.github/workflows/frontend-tests.yml` — check de Pull Request que ejecuta la prueba de
  congruencia junto con la suite frontend.
- `frontend/features/shell/components/version-badge.tsx` — `formatBuildVersion` y el badge:
  solo composición y presentación.
- `frontend/features/shell/components/shell-footer.tsx`, `shell-frame.tsx` — pie y slot `footer`.
- `frontend/locales/{es,en}/common.json` — claves `version.*`.
- `docker-compose.yml` — las dos `NEXT_PUBLIC_*` del servicio `frontend` en dev local.
- `docs/app-version-visibility.md` — cómo se opera; `infra/environments/dev/RUNBOOK.md` §6.4 y §7.

## Estado

Desplegado en `dev` el 2026-07-31 en dos pasos: `app-version-visibility` (PR #27, merge
`5872022`) puso el badge con la forma corta, y `app-version-badge-date` (PR #28, merge
`d30ad7d`) lo pasó a la cadena canónica completa y movió el veto de forma al límite del
snapshot público.

Verificado que el badge aparece en `/login`, `/dashboard`, `/cleaner` y `/tech` y está ausente
en `/guest/<token>`. La legibilidad en móvil está **medida**, no supuesta: 181×23 px en una
línea, sin desbordamiento a 390, 360 ni 320 px de ancho, y 7 px de separación sobre el
`BottomNavigation` fijo. Y el veto del límite está comprobado end-to-end: con un
`NEXT_PUBLIC_APP_VERSION` envenenado (SHA de 40 caracteres más `run_id`), ni el HTML de `/login`
ni el de `/guest/<token>` contienen esos valores, y el snapshot rinde `appVersion: ""`.

**Pendiente de comprobar sobre la VM**: que los labels OCI permitidos hayan aterrizado en las
imágenes publicadas. El job `provenance` comparte la identidad pública `version` con ambos
builds; el backend conserva además `source` y SHA completo, mientras que el frontend queda
limitado a SHA corto, `version` y `created`. La inspección de packages privados requiere acceso
`read:packages`.

La congruencia entre el productor CD y esta frontera pública se verifica en la prueba de
contrato ejecutada por el check `frontend-tests` en los Pull Requests. La verificación falla si
la forma producida deja de ser aceptada por el contrato vigente.
