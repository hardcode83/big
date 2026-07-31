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

- [ ] 2.1 **Medir**, no suponer. Levantar el frontend local con la cadena larga horneada
  (`NEXT_PUBLIC_APP_VERSION=0.1.0+2026-07-31.5872022 docker compose up -d frontend`; el
  servicio ya declara la variable con default `local` y **no tiene `env_file`**), y con
  Playwright a **390×844** (iPhone 12/13/14), **360** (Android común) y **320** (iPhone SE,
  el caso duro) comprobar en `/login` y en el workspace —que es el único shell con
  `BottomNavigation` fijo— que: (a) `documentElement.scrollWidth <= clientWidth`, o sea
  ningún desbordamiento horizontal de la página; (b) el badge no se solapa con la barra
  inferior (comparar `getBoundingClientRect()` del `footer` y del `nav` fijo). Anotar los
  píxeles medidos en la tarea al cerrarla — el número es la evidencia, no el "se ve bien".
  — files: ninguno (verificación) [R2.1]

- [ ] 2.2 Según lo medido en 2.1, **una de dos**, y se escribe cuál: si cabe con holgura, se
  cierra la tarea anotando el ancho del badge frente al del viewport y no se toca el
  componente; si no cabe, se **acomoda** —truncado visual con la cadena completa accesible, o
  salto de línea— y **nunca** se revierte a la forma corta. Si la acomodación introduce
  cualquier string visible nueva (un tooltip, por ejemplo), va a `locales/es/` **y**
  `locales/en/` en la misma tarea, por `steering/frontend.md`; el `aria-label` actual ya
  nombra el valor completo y no necesita clave nueva.
  — files: `version-badge.tsx` y `locales/{es,en}/common.json` **solo si hace falta** [R2.2]

## 3. El registro deja de prescribir el recorte

- [ ] 3.1 `docs/app-version-visibility.md`: el ejemplo de la línea 17 pasa a la cadena
  completa, y el aviso del tag mutable (líneas 45-49) se reescribe. **Corrección de la
  premisa de R3.2**: no es cierto que con la fecha visible el badge distinga dos builds
  cualesquiera del mismo commit — la fecha canónica tiene granularidad de **día**
  (`%Y-%m-%d`), así que dos rebuilds del mismo commit **el mismo día** siguen siendo
  idénticos en el badge, y ese es justo el caso del `workflow_dispatch` para recuperar un
  deploy fallido. El aviso debe quedar en: el badge ya separa builds de días distintos; para
  el mismo día sigue haciendo falta `org.opencontainers.image.created`, que lleva la hora.
  — files: `docs/app-version-visibility.md` [R3.2]

- [ ] 3.2 Dejar el registro coherente **sin reescribir el archivo histórico**. R3.1 pide
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

- [ ] 4.1 Suite completa del frontend en verde: `cd frontend && npm test` [R1, R2]
- [ ] 4.2 Lint y typecheck: `cd frontend && npm run lint && npm run typecheck` [R1]
- [ ] 4.3 Comprobación de que la nueva expectativa es **portante**: revertir a mano el recorte
  en `formatBuildVersion` (volver a `${base}+${short}`) y confirmar que los tests de 1.2
  **fallan**; deshacer. Un test que pasa con las dos implementaciones no prueba nada, y este
  change entero consiste en un cambio de valor esperado. [R1.1]
- [ ] 4.4 Comprobación manual end-to-end en local: con la cadena larga horneada (2.1), el
  badge muestra `0.1.0+2026-07-31.5872022` en `/login`, en el workspace y en `/cleaner`, y
  **sigue ausente** en `/guest/<token>` — la exclusión del portal de huésped es del change
  padre y esta tarea la protege de regresión. [R1.1, R2.1]

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
| R3.2 `docs/` actualizada | 3.1 |
