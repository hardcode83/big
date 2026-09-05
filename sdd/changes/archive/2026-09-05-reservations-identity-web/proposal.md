# Proposal: reservations-identity-web

## Why

`reservation-property-identity` (mergeado el 2026-08-25, archivado en
`sdd/changes/archive/2026-08-30-reservation-property-identity/`) añadió los campos derivados
`property_name`, `property_internal_code` y `guest_full_name` a `GET /api/v1/reservations` y a
`GET /api/v1/reservations/{id}` (contrato ya documentado en `sdd/specs/reservations.md:89-134,
380-381`). Medido el 2026-08-30 y revalidado el 2026-09-05, el frontend no consume ninguno de los
tres: `frontend/features/reservations/components/list/reservations-view.tsx:172` sigue pintando
`{row.propertyId}` (un UUID) en la columna *Property*, la columna *Guest* pinta `row.guestId`, y el
detalle no muestra la identidad de la propiedad en absoluto. Es la mitad `[FE]` que cierra el
defecto que `reservations-web` dejó abierto: la maqueta de Stitch mostraba `REDES11`, no
`981b5c2e-…`.

`reservation-create-web` está detrás en el roadmap (`needs: reservations-identity-web`) para no
construir el formulario de alta sobre una lista que todavía identifica la vivienda por UUID.

## What changes

El DTO (`frontend/features/reservations/data/dto.ts`) y el mapper
(`frontend/features/reservations/data/http/http-reservations-source.ts`) se amplían con los tres
campos ya presentes en `frontend/lib/api/generated/openapi.d.ts`
(`ReservationResponse`/`ReservationDetailResponse`, líneas 4077/4101/4103 y 4169/4193/4195 — el
contrato ya está regenerado, no hace falta tocar `openapi.json` ni el generador). La lista
(`reservations-view.tsx`) pinta `propertyInternalCode` en la celda de *Property* (con
`propertyName` como `title` del mismo `<td>`) y `guestFullName` en la celda de *Guest*, sustituyendo
los dos ids crudos. El detalle gana un bloque de identidad de propiedad (hoy inexistente en
`composeDetailSections`) con `propertyInternalCode` y `propertyName`; el guest block ya existente
no cambia (ya pinta `guest.fullName` desde el objeto anidado). Los tres campos son `nullable` en el
contrato: cualquier ausencia se pinta con el em-dash `—` literal, la regla ya vigente en
`sdd/specs/frontend-foundation.md:45` y ya usada en el propio fichero (`grossAmount`, `guestId`).
Sin backend: no se toca `openapi.json`, el generador, ni ningún endpoint.

## Requirements

### R1 — DTO y mapper llevan los tres campos derivados

**As a** frontend engineer, **I want** los DTOs de reserva y su mapper HTTP expuestos con
`propertyName`, `propertyInternalCode` y `guestFullName`, **so that** los componentes de lista y
detalle puedan pintarlos sin volver a tocar el mapper.

Acceptance criteria:

1. WHEN se mapea una fila de `GET /api/v1/reservations` (`ReservationResponse`), THE SYSTEM SHALL
   incluir `propertyName: string | null`, `propertyInternalCode: string | null` y
   `guestFullName: string | null` en `ReservationSummaryDto`, leídos de
   `property_name`/`property_internal_code`/`guest_full_name`.
2. WHEN se mapea `GET /api/v1/reservations/{id}` (`ReservationDetailResponse`), THE SYSTEM SHALL
   heredar los mismos tres campos en `ReservationDetailDto` (por herencia de
   `ReservationSummaryDto`) sin duplicar el mapeo.
3. IF el campo llega `null` o ausente en la respuesta, THEN THE SYSTEM SHALL mapearlo a `null` en
   el DTO — nunca `undefined` ni cadena vacía.

### R2 — Columna *Property* de la lista pinta el código, no el UUID

**As a** manager, **I want** ver el código interno de la vivienda (y su nombre como referencia) en
cada fila de `/reservations`, **so that** pueda identificarla sin cruzar el UUID a mano.

Acceptance criteria:

1. WHEN una fila tiene `propertyInternalCode` no nulo, THE SYSTEM SHALL pintarlo en la celda
   *Property* de la tabla (sustituyendo `row.propertyId`), con `propertyName` en el atributo
   `title` de la misma celda cuando no sea nulo.
2. IF `propertyInternalCode` es `null`, THEN THE SYSTEM SHALL pintar el em-dash `—` literal en la
   celda (nunca `row.propertyId` como fallback).

### R3 — Columna *Guest* de la lista pinta el nombre, no el UUID

**As a** manager, **I want** ver el nombre del huésped en cada fila de `/reservations`, **so
that** no tenga que abrir el detalle para saber quién es.

Acceptance criteria:

1. WHEN una fila tiene `guestFullName` no nulo, THE SYSTEM SHALL pintarlo en la celda *Guest*
   (dentro del mismo `<Link>` de navegación a la fila, sustituyendo `row.guestId`).
2. IF `guestFullName` es `null`, THEN THE SYSTEM SHALL pintar el em-dash `—` literal, preservando
   el enlace de navegación de la fila.

### R4 — El detalle muestra la identidad de la propiedad

**As a** manager, **I want** ver el código y el nombre de la vivienda en
`/reservations/[id]`, **so that** el detalle no dependa de que la lista ya se lo haya enseñado.

Acceptance criteria:

1. WHEN se renderiza el detalle, THE SYSTEM SHALL mostrar un bloque de propiedad con
   `propertyInternalCode` y `propertyName`, siguiendo el mismo patrón `dl`/`dt`/`dd` que los demás
   bloques de `reservation-detail-sections.tsx`.
2. IF cualquiera de los dos campos es `null`, THEN THE SYSTEM SHALL pintar el em-dash `—` literal
   en su `dd` correspondiente, sin ocultar el bloque entero.

### R5 — i18n y ausencia de strings hardcodeadas

**As a** frontend engineer, **I want** que cualquier etiqueta nueva viva en
`locales/{es,en}/reservations.json`, **so that** el revisor `sdd-review-i18n` no encuentre texto
hardcodeado.

Acceptance criteria:

1. WHEN el bloque de propiedad del detalle necesita una etiqueta de sección, THE SYSTEM SHALL
   reutilizar la clave existente `fields.property` (ya presente en ambos locales para la cabecera
   de la lista) en vez de crear una nueva si su texto encaja; si no encaja, THE SYSTEM SHALL añadir
   la clave nueva a **ambos** `locales/es/reservations.json` y `locales/en/reservations.json`.
2. THE SYSTEM SHALL NOT introducir el em-dash como clave de i18n (es un carácter literal, regla ya
   fijada en `frontend-foundation.md:45`).

### R6 — Cobertura de test para los tres campos y sus nulos

**As a** frontend engineer, **I want** que el mapper y los dos componentes tengan un test por
campo nuevo y por su caso `null`, **so that** una regresión futura en el mapeo o el render se
detecte en `npm test`.

Acceptance criteria:

1. WHEN se ejecuta `http-reservations-source.test.ts`, THE SYSTEM SHALL cubrir el mapeo de
   `property_name`/`property_internal_code`/`guest_full_name` presentes y `null` para ambos
   endpoints (lista y detalle).
2. WHEN se ejecuta `reservations-view.test.tsx`, THE SYSTEM SHALL cubrir la fila con los tres
   campos presentes y la fila con los tres en `null` (em-dash, sin fallback a los ids).
3. WHEN se ejecuta `reservation-detail-view.test.tsx` (o el test del nuevo bloque en
   `reservation-detail-sections`), THE SYSTEM SHALL cubrir el bloque de propiedad con valores y con
   `null`.

## Out of scope

- Regenerar `openapi.json` o el generador de tipos — el contrato ya está regenerado en
  `frontend/lib/api/generated/openapi.d.ts` (verificado leyendo el fichero: los tres campos ya
  están declarados como opcionales/nullable en `ReservationResponse` y
  `ReservationDetailResponse`).
- Crear, editar o cancelar una reserva (`reservation-create-web`, detrás en el roadmap).
- Filtrar la lista por propiedad o enlazar la celda de *Property* a `/properties/[id]` — candidato
  menor si sale gratis, pero no forma parte de este `size: S`.
- Tocar el backend, `openapi.json` o cualquier endpoint.
- Cambiar el bloque de huésped del detalle (`DetailGuestBlock`) — ya pinta `guest.fullName` desde
  el objeto anidado `guest`, que no cambia con este proposal.

## Affected specs

- `sdd/specs/frontend-foundation.md` — la entrada de "Key files" (línea 106) y la nota de la ruta
  `/reservations`/`/reservations/[id]` en el bullet de placeholders (línea 27) se actualizan para
  decir que la lista y el detalle pintan identidad de propiedad/huésped en vez de UUIDs. El
  contrato de datos (`property_name`, `property_internal_code`, `guest_full_name`) ya está
  documentado en `sdd/specs/reservations.md:89-134,380-381` y no cambia.
