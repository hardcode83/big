# Tasks: app-version-badge-date

Sin `design.md` a propósito: una función, ningún fichero nuevo, ninguna decisión de
arquitectura. Las dos decisiones que sí hay se resuelven dentro de las tareas 1.1 y 2.2 y se
dejan escritas ahí.

## 1. El badge deja de recortar

- [x] 1.1 `formatBuildVersion` devuelve la **cadena canónica completa** en vez de recomponer
  `base+sha`. Contrato nuevo: si la cadena lleva metadatos de build (tiene `+`), se devuelve
  tal cual (con la fecha); si no los lleva (el `local` de dev), se devuelve la base, y solo
  entonces se le añade el sha corto si viene horneado. Las degradaciones del change padre
  siguen intactas: `null` —no `""`— cuando la cadena está vacía **o cuando su base queda
  vacía** (`"+"`, `"  +abc123"`, `"++"`, `" + "`), y trim en ambas entradas.
  **Decisión tomada aquí**: se conserva el segundo parámetro `buildCommitShort`. Con la
  cadena completa el sha ya viaja dentro de ella, así que la alternativa era reducir la firma
  a un argumento — se descarta porque dejaría el campo `buildCommitShort` de la allowlist de
  `PublicRuntimeConfig` **sin ningún consumidor**, y un campo público que nadie lee es peor
  que un parámetro con un solo caso de uso. Quitarlo de la allowlist queda fuera de alcance
  (toca 4 ficheros y contradice la spec recién escrita).
  — files: `frontend/features/shell/components/version-badge.tsx` [R1.1, R1.2, R1.3]

  **Segunda decisión, del panel de la sección 1 — la identidad horneada se valida en el
  límite, no en el badge.** `buildPublicRuntimeConfig()` (`lib/config/public.ts`) solo admite
  dos formas: `<base>` a secas (el `local` de dev) y `<base>+YYYY-MM-DD.<7 hex>`; el
  `buildCommitShort` solo `[0-9a-f]{7}`. Cualquier otra cosa cae a `""`, que es el caso "sin
  identidad" que el badge ya rinde como "versión desconocida".

  Referentes: la sección **"Alcance de la divulgación, aceptado"** de
  `sdd/specs/app-version-visibility.md` y su prohibición de líneas 67-70 (el SHA completo, el
  número de PR, el `run_id` y el `ref` **no** pueden estar en el snapshot público), más
  **R1.2** para la parte presentacional (ninguna cadena con forma de versión a medias).

  El motivo es estructural y lo encontró el panel de seguridad: **hasta este change los
  metadatos se descartaban** y se sustituían por el sha corto, así que compusiera lo que
  compusiera el CD solo 7 caracteres podían llegar a pantalla. Mostrarlos completos elimina
  ese límite, y el guard que existía **seguía verde** porque plantaba los valores sensibles en
  variables que el componente no lee.

  **Tres iteraciones, y las dos primeras estaban mal — conviene que quede escrito:**
  1. Validar en `formatBuildVersion` con `[0-9a-f]{7,12}`. Seguridad demostró que los dígitos
     decimales son un **subconjunto** del hex, así que un `run_id` de Actions (11 dígitos)
     pasaba como si fuera un commit. La tolerancia *era* el agujero.
  2. Seguía validando solo el `appVersion`, cuando `buildCommitShort` es **el destino de toda
     degradación** y el CD lo compone en la línea de al lado (`commit_short=${GITHUB_SHA:0:7}`):
     el mismo descuido que ensancha uno ensancha el otro, así que el camino "seguro" publicaba
     el SHA de 40 caracteres.
  3. Y sobre todo: **la capa era la equivocada.** Arquitectura lo reprodujo con un
     `next build` real — React serializa el snapshot como prop en el payload RSC del layout
     raíz, así que un valor envenenado viaja en el código fuente de **todas** las superficies,
     incluida `/guest/<token>`, pase lo que pase con el badge. Validar en el componente solo
     limpiaba los píxeles. Verificado ya sobre el servidor real: con el valor envenenado, ni
     `/login` ni `/guest/<token>` contienen el SHA ni el run id, y el payload lleva
     `appVersion: ""`.

  Lo que queda en el componente es presentación: componer la cadena y no pintar nunca una
  versión a medias. Consecuencia asumida: si el esquema canónico cambia (una hora, por
  ejemplo) hay que cambiar el patrón del límite con él, o el badge cae a "desconocida" sin
  avisar — nada lo detecta hoy, y eso queda anotado como candidato en la sección 5.

- [x] 1.2 Ajustar `version-badge.test.tsx` a la nueva expectativa. Los tests que hoy afirman
  el recorte y **tienen que cambiar de valor esperado**, no de intención: el de la línea 15
  (`shortens the canonical string…` → la cadena completa), el de whitespace de la línea 49
  (` 0.1.0+x.y ` → `0.1.0+x.y`, no `0.1.0+a2f3c1d`), el de render de la 72 y el del nombre
  accesible de la 91 (`Versión desplegada: 0.1.0+2026-07-30.a2f3c1d`). **No se toca** el
  bloque `it.each` de bases vacías ni el guard de fuga por `innerHTML` — cubren R1.2 y siguen
  siendo la red de seguridad. Añadir el caso que hoy no existe: cadena **con** metadatos y sha
  corto horneado a la vez, que es la forma real de producción, para fijar que el sha no se
  duplica al final. — files: `frontend/features/shell/components/version-badge.test.tsx`
  [R1.1, R1.2, R1.3]

- [x] 1.3 Reescribir el comentario de cabecera de `formatBuildVersion`, que hoy **argumenta
  el recorte** ("with the date it is ~24 characters and competes for room in a phone's
  chrome") y quedaría contradiciendo al código. Debe decir por qué se muestra completa: la
  fecha es lo único que separa builds distintos, y el panel donde iba a verse no existe.
  — files: `frontend/features/shell/components/version-badge.tsx` [R1.1, R3.1]

- [x] 1.4 **No estaba en el checklist; sin R#.** Añadida al descubrir que la suite del
  frontend estaba **roja en `main`**, no por este change: 27 tests en 4 ficheros de shell
  caían con `window.localStorage.clear is not a function`. Causa: **Node 25 expone un
  `localStorage` global propio** (Web Storage ya sin flag, respaldado por
  `--localstorage-file`), el `window` de jsdom lo recoge, y el guard de `test/setup.ts`
  —`if (!window.localStorage)`— lo veía *truthy* y por eso **no instalaba el polyfill**,
  dejando un objeto sin `clear`. El guard pasa a detectar los **métodos** (`clear`,
  `getItem`, `setItem`) en vez de la existencia del objeto. Sin esto la tarea 4.1 no se
  puede cumplir ni afirmar honestamente. Solo toca infraestructura de test, ninguna línea
  de producción. — files: `frontend/test/setup.ts`

## 2. La legibilidad en móvil, medida

- [x] 2.1 **Medir**, no suponer. Levantar el frontend local con la cadena larga horneada
  (`NEXT_PUBLIC_APP_VERSION=0.1.0+2026-07-31.5872022 docker compose up -d frontend`; el
  servicio ya declara la variable con default `local` y **no tiene `env_file`**), y con
  Playwright a **390×844** (iPhone 12/13/14), **360** (Android común) y **320** (iPhone SE,
  el caso duro) comprobar en `/login` y en el workspace —que es el único shell con
  `BottomNavigation` fijo— que: (a) `documentElement.scrollWidth <= clientWidth`, o sea
  ningún desbordamiento horizontal de la página; (b) el badge no se solapa con la barra
  inferior (comparar `getBoundingClientRect()` del `footer` y del `nav` fijo). Anotar los
  píxeles medidos en la tarea al cerrarla — el número es la evidencia, no el "se ve bien".
  — files: ninguno (verificación) [R2.1]

  **Medido** con la cadena real `0.1.0+2026-07-31.5872022` (24 caracteres) servida por el
  contenedor de dev, en Chromium vía Playwright. El badge mide **181×23 px** —una sola
  línea— y es idéntico en los tres anchos, porque el texto no llega a competir por el
  espacio:

  | viewport | superficie | `scrollWidth`/`clientWidth` | holgura a la derecha | separación de la barra fija |
  | --- | --- | --- | --- | --- |
  | 390 | `/login` | 390 / 390 — sin desbordamiento | 193 px | (sin barra: `PublicShell`) |
  | 390 | `/dashboard` | 390 / 390 — sin desbordamiento | 193 px | **+7 px** (pie 780, barra 787) |
  | 360 | `/login` | 360 / 360 — sin desbordamiento | 163 px | (sin barra) |
  | 320 | `/login` | 320 / 320 — sin desbordamiento | 123 px | (sin barra) |
  | 320 | `/dashboard` | 320 / 320 — sin desbordamiento | 123 px | **+7 px** (pie 504, barra 511) |

  Ni desbordamiento de la página ni del propio badge (`scrollWidth === clientWidth` también
  dentro del elemento, así que no hay texto recortado). El workspace se pudo medir de verdad
  porque `/dashboard` responde 200 **sin sesión** —el frontend todavía no tiene auth— y es el
  único shell que pinta `BottomNavigation`; su columna sigue llevando
  `flex min-w-0 flex-1 flex-col pb-16 md:pb-0`, que es lo que produce esos 7 px.

- [x] 2.2 Según lo medido en 2.1, **una de dos**, y se escribe cuál: si cabe con holgura, se
  cierra la tarea anotando el ancho del badge frente al del viewport y no se toca el
  componente; si no cabe, se **acomoda** —truncado visual con la cadena completa accesible, o
  salto de línea— y **nunca** se revierte a la forma corta. Si la acomodación introduce
  cualquier string visible nueva (un tooltip, por ejemplo), va a `locales/es/` **y**
  `locales/en/` en la misma tarea, por `steering/frontend.md`; el `aria-label` actual ya
  nombra el valor completo y no necesita clave nueva.
  — files: `version-badge.tsx` y `locales/{es,en}/common.json` **solo si hace falta** [R2.2]

  **Cabe con holgura: no se toca el componente y no hay strings nuevas.** 181 px de badge
  frente a 320 px del viewport más estrecho que se contempla — el 57 %, y con 123 px libres
  a su derecha. La preocupación que motivó el recorte original ("con la fecha son ~24
  caracteres que compiten por el espacio en un móvil") era razonable a priori y resulta ser
  infundada: a 11 px en `font-mono` esos 24 caracteres ocupan menos de la mitad del ancho
  incluso en un iPhone SE. Que la acomodación no haya hecho falta es un resultado de la
  medición, no una decisión de saltársela.

## 3. El registro deja de prescribir el recorte

- [x] 3.1 `docs/app-version-visibility.md`: el ejemplo de la línea 17 pasa a la cadena
  completa, y el aviso del tag mutable (líneas 45-49) se reescribe. **Corrección de la
  premisa de R3.2**: no es cierto que con la fecha visible el badge distinga dos builds
  cualesquiera del mismo commit — la fecha canónica tiene granularidad de **día**
  (`%Y-%m-%d`), así que dos rebuilds del mismo commit **el mismo día** siguen siendo
  idénticos en el badge, y ese es justo el caso del `workflow_dispatch` para recuperar un
  deploy fallido. El aviso debe quedar en: el badge ya separa builds de días distintos; para
  el mismo día sigue haciendo falta `org.opencontainers.image.created`, que lleva la hora.
  — files: `docs/app-version-visibility.md` [R3.2]

  **Mi inventario estaba incompleto.** La tarea nombraba solo `docs/`, pero la forma corta
  aparecía también en **`README.md:105`** y en el **`RUNBOOK.md` §6.4**. Los exige
  `steering/documentation.md` ("el README describe el sistema *actual*"), no R3.2, así que la
  tarea creció al ejecutarla. Los tres explican ahora el matiz de granularidad de día. El
  revisor de documentación barrió el repo entero después y no encontró ninguno más.

- [x] 3.2 Dejar el registro coherente **sin reescribir el archivo histórico**. R3.1 pide
  corregir "el criterio del change padre", pero `app-version-visibility` ya está archivado en
  `sdd/changes/archive/2026-07-31-app-version-visibility/`, y las reglas del flujo prohíben
  reescribir archivos históricos: su `proposal.md:78` y su `design.md:150` son el registro
  veraz de lo que se decidió entonces, con su premisa (el panel de procedencia) incluida. El
  documento que **sí** manda hoy y que hay que corregir es la spec viva, y se corrige al
  archivar este change, no ahora — `sdd/specs/` se mantiene solo al archivar
  (`steering/documentation.md`). Renglones exactos, enumerados aquí para que el archivado no
  tenga que redescubrirlos:
  `sdd/specs/app-version-visibility.md:54-55` (dice "en la forma corta `<base>+<sha-corto>`"),
  `:118-120` (el aviso del tag mutable, con el matiz de granularidad de día de 3.1) y
  `:147-150` (la nota de "mejora ya identificada", que pasa a hecha). Esta tarea se cierra
  cuando esos tres renglones están enumerados y verificados como los únicos, no cuando están
  editados. — files: ninguno (hand-off al archivado) [R3.1]

## 4. Verification

- [x] 4.1 Suite completa del frontend en verde: `cd frontend && npm test` [R1, R2]
  → **189/189 en 35 ficheros**. Partía de 178 (27 de ellos rojos antes de la tarea 1.4).
- [x] 4.2 Lint y typecheck: `cd frontend && npx eslint . && npm run typecheck` [R1]
  → ambos limpios. (El comando de `project.md` dice `npm run lint`; `npx eslint .` es
  literalmente lo que ese script ejecuta.)
- [x] 4.3 Comprobación de que la nueva expectativa es **portante**: revertir a mano el recorte
  en `formatBuildVersion` (volver a `${base}+${short}`) y confirmar que los tests de 1.2
  **fallan**; deshacer. Un test que pasa con las dos implementaciones no prueba nada, y este
  change entero consiste en un cambio de valor esperado. [R1.1]

  Dos mutaciones, corridas **después** del arreglo del panel (el código cambió desde que QA
  hizo su barrido, así que su tabla ya no valía como evidencia):
  quitar la composición de metadatos → **6 tests caen**; abrir el límite para que
  `allowlistedShape` devuelva el valor sin comprobar → **9 tests caen**. Ficheros restaurados
  desde copia y suite verde otra vez. QA había probado además `rest[0]` en vez de
  `rest.join("+")`, quitar el guard de base vacía y colar un `title={REPO_URL}`: ninguna
  sobrevivió.
- [x] 4.4 Comprobación manual end-to-end en local: con la cadena larga horneada (2.1), el
  badge muestra `0.1.0+2026-07-31.5872022` en `/login`, en el workspace y en `/cleaner`, y
  **sigue ausente** en `/guest/<token>` — la exclusión del portal de huésped es del change
  padre y esta tarea la protege de regresión. [R1.1, R2.1]

  Las cinco superficies contra el contenedor real: `/login`, `/dashboard`, `/cleaner` y
  `/tech` muestran `0.1.0+2026-07-31.5872022`; `/guest/<token>` **sin badge**. Y la prueba que
  cierra el hallazgo del arquitecto: recreando el contenedor con un `NEXT_PUBLIC_APP_VERSION`
  envenenado (SHA de 40 caracteres + run id), **ni el HTML de `/login` ni el de
  `/guest/<token>` contienen el SHA ni el run id**, y el payload RSC lleva `appVersion: ""`.
  Ese es el mismo método con el que él demostró el agujero.

## 5. Candidatos para más adelante (no se hacen aquí)

Ninguno es tarea de este change; quedan escritos para que no se pierdan con la sesión.

- **Deriva entre el productor y el que valida.** Nada comprueba que la cadena que el CD
  compone de verdad satisfaga el patrón del límite. Si alguien ensancha `${GITHUB_SHA:0:7}` a
  8 caracteres, el badge cae a "versión desconocida" y **ningún test ni paso del pipeline
  falla**. Lo señalaron seguridad y arquitectura por separado. Se cerraría con un check en el
  workflow, o con un test que lea `deploy-dev.yml` y afirme la forma de la composición.
- **La cita "R2.4"** que arrastran `lib/config/public.ts:35` y varios tests: en el change
  padre R2.4 es "añadir los dos campos a la allowlist", no la prohibición del SHA/`run_id`,
  que es prosa de la sección "Alcance de la divulgación, aceptado". La cita preexiste a este
  change; corregirla en todos sus sitios es una limpieza aparte.
- **Tamaño y contraste del badge** (11 px, `text-muted-foreground`) y el **404 de
  `favicon.ico`**: ya declarados fuera de alcance en el proposal.

## Cobertura de requisitos

| Requisito | Tareas |
| --- | --- |
| R1.1 cadena canónica completa | 1.1, 1.2, 1.3, 4.3, 4.4 |
| R1.2 degradaciones intactas | 1.1, 1.2 |
| R1.3 `local` tal cual | 1.1, 1.2 |
| R1.4 sin red, legible en móvil | 2.1, 2.2 (sin red: no se añade ninguna llamada) |
| R2.1 medición en viewport real | 2.1, 4.4 |
| R2.2 acomodar, no revertir | 2.2 |
| R3.1 el registro no pide el recorte | 1.3, 3.2 |
| R3.2 `docs/` actualizada | 3.1 (+ README y RUNBOOK, por `steering/documentation.md`) |
