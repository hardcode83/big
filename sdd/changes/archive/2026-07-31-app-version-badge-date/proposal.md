# Proposal: app-version-badge-date

## Why

El badge que `app-version-visibility` acaba de desplegar muestra `0.1.0+5872022`. La cadena
canónica que el CD compone y que llevan los labels OCI es `0.1.0+2026-07-31.5872022` — **con
la fecha de build**. El badge la recorta.

Ese recorte fue una decisión deliberada (pregunta abierta OQ2 de aquel change): la forma
corta en el badge *porque la fecha se mostraría en el panel de procedencia*, y con la fecha
completa son ~24 caracteres que compiten por el espacio en un móvil.

**Después, el recorte de alcance de aquel change eliminó el panel.** Con él desapareció el
único sitio de la UI donde la fecha iba a verse, y nadie revisó si el badge debía dejar de
acortarse. La premisa de OQ2 era "hay otro sitio donde mirarla", y ese sitio ya no existe.

Hoy la fecha de build solo es accesible por `docker inspect` desde la VM o leyendo el código
fuente de la página. Eso contradice el propósito del change padre: *saber qué está desplegado
sin entrar en la VM*.

Y la fecha importa por una razón concreta, ya documentada en
`docs/app-version-visibility.md`: el despliegue pinea por el tag mutable `sha-<commit>`, no
por dígest, así que **la forma corta es idéntica para dos builds distintos del mismo commit**.
Solo la fecha los distingue. Un rebuild del mismo commit —un `workflow_dispatch` para
recuperar un deploy fallido, por ejemplo— es indistinguible en el badge actual.

## What changes

El badge pasa a mostrar la cadena canónica completa, con la fecha:

```
antes:    0.1.0+5872022
después:  0.1.0+2026-07-31.5872022
```

Es dejar de recortar en `formatBuildVersion`, más el ajuste de sus tests y la corrección del
criterio del change padre que prescribía la forma corta.

## Requirements

### R1 — El badge muestra la cadena canónica completa

**As a** operador, **I want** ver también la fecha de build en el badge, **so that** pueda
distinguir dos builds del mismo commit sin entrar en la VM.

Acceptance criteria:

1. WHEN la imagen lleva identidad horneada, THE SYSTEM SHALL mostrar en el badge la cadena
   canónica tal como la compuso el CD, incluida la fecha de build
   (`<base>+<fecha>.<sha-corto>`), sin recortarla.
2. THE SYSTEM SHALL seguir mostrando el texto localizado de "versión desconocida" cuando la
   imagen no lleve identidad, y THE SYSTEM SHALL NOT mostrar nunca un badge vacío ni una
   cadena con forma de versión a medias — las degradaciones que el change padre ya cubría
   siguen vigentes.
3. WHERE la cadena no contiene metadatos de build (el `local` de dev), THE SYSTEM SHALL
   mostrarla tal cual.
4. THE SYSTEM SHALL mantener el badge sin ninguna petición de red y legible en móvil
   (mobile-first, `steering/frontend.md`).

### R2 — La legibilidad en móvil se comprueba, no se supone

**As a** propietaria que opera desde el móvil, **I want** que el badge siga siendo usable con
la cadena más larga, **so that** no se desborde ni empuje el resto del pie.

Acceptance criteria:

1. THE SYSTEM SHALL verificar el pie en un viewport de móvil real (≤390px de ancho) con la
   cadena completa, y THE SYSTEM SHALL NOT provocar desbordamiento horizontal de la página ni
   solapamiento con el `BottomNavigation` fijo.
2. IF la cadena completa no cabe con holgura en ese viewport, THEN THE SYSTEM SHALL adaptar la
   presentación (truncado con la cadena completa accesible, o salto de línea) en vez de
   revertir a la forma corta — la información no se sacrifica, se acomoda.

### R3 — El registro deja de prescribir la forma corta

**As a** quien lea las specs después, **I want** que no quede ningún documento pidiendo el
recorte, **so that** el registro no contradiga al código.

Acceptance criteria:

1. THE SYSTEM SHALL corregir el criterio del change padre que prescribe "la forma corta
   `<base>+<sha-corto>`", y THE SYSTEM SHALL dejar constancia de que OQ2 se decidió sobre una
   premisa —el panel de procedencia— que el recorte de alcance eliminó.
2. THE SYSTEM SHALL actualizar `docs/app-version-visibility.md`, cuyo ejemplo muestra la forma
   corta y cuyo aviso sobre el tag mutable deja de aplicar en los mismos términos: con la
   fecha visible, el badge **ya distingue** dos builds del mismo commit.

## Out of scope

- **El tamaño y el contraste del badge** (11px, `text-muted-foreground`). Es una crítica
  justa a mi propia elección, pero es una decisión de diseño visual independiente de que la
  fecha se muestre. Si se quiere, entrada aparte.
- **El 404 de `favicon.ico`** que aparece en la consola de producción: preexistente, ajeno a
  esta capacidad.
- **Pinear por dígest en vez de por tag mutable.** Es la causa raíz de que dos builds del
  mismo commit sean confundibles; mostrar la fecha lo mitiga en la UI, no lo arregla. Decisión
  de infraestructura, no de este change.
- **Cualquier reintroducción del panel de procedencia o de los enlaces al PR** → sigue en
  `app-version-provenance`, bloqueada hasta que el frontend tenga autenticación.

## Affected specs

- `sdd/specs/app-version-visibility.md` — modificar *(no existe aún: la creará el
  `/sdd:archive` de `app-version-visibility`, que está mergeado pero sin archivar)*. **Nota de
  orden**: conviene archivar el change padre antes de implementar este, para que la spec
  nazca ya con la cadena completa en vez de nacer con la forma corta y corregirse acto
  seguido.

Fuera de `sdd/specs/`: `frontend/features/shell/components/version-badge.tsx` y su test,
`sdd/changes/app-version-visibility/proposal.md` (R2.1) y `docs/app-version-visibility.md`.
